import React, { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Mic, Square, Paperclip, Bot, User, Search, CheckCircle2, FileText,
         Volume2, X, Plus, Trash2, MessagesSquare, Sparkles, Loader2, ChevronDown,
         AudioLines, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { api, chatStream, TYPE_AR } from "../lib/api.js";
import { useToast } from "../components/Toast.jsx";
import { useConfirm } from "../components/Confirm.jsx";
import { matchBadge } from "./Details.jsx";
import { createVoiceSession } from "../lib/voice.js";
import AudioPlayer from "../components/AudioPlayer.jsx";

const PRESETS = {
  restaurant: ["إيه أشهر أطباقكم؟", "بكام الكشري؟", "المطعم بيفتح الساعة كام؟",
               "فين العنوان بالظبط؟", "عندكم أصناف نباتية؟", "إيه عروض الأسبوع؟"],
  customer_service: ["إزاي أرجّع منتج؟", "مواعيد الدعم إيه؟", "إيه سياسة الاستبدال؟", "إزاي أتابع طلبي؟"],
  healthcare: ["إزاي أحجز معاد؟", "مواعيد العيادة إيه؟", "محتاج تحضير قبل الكشف؟", "فين العيادة؟"],
  education: ["إيه المواضيع المتاحة؟", "إزاي أبدأ؟", "فين الملخصات؟", "إيه مواعيد المحاضرات؟"],
  other: ["إيه اللي تقدر تساعدني فيه؟", "اعرض لي المعلومات المتاحة", "إيه مواعيد العمل؟"],
};

export default function Chat({ cfg }) {
  const [sessions, setSessions] = useState([]);
  const [sid, setSid] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [partial, setPartial] = useState("");
  const [preview, setPreview] = useState(null);
  const [sessCollapsed, setSessCollapsed] = useState(() => localStorage.getItem("va-sess") === "1");
  const scroller = useRef(); const drip = useRef({ target: "", timer: null });
  const vs = useRef(null);
  const toast = useToast();
  const confirm = useConfirm();
  useEffect(() => { localStorage.setItem("va-sess", sessCollapsed ? "1" : "0"); }, [sessCollapsed]);

  const presets = PRESETS[cfg.agent?.category] || PRESETS.other;
  const loadSessions = () => api.sessions().then((r) => setSessions(r.sessions || [])).catch(() => {});
  useEffect(() => { loadSessions(); }, []);
  useEffect(() => { scroller.current?.scrollTo({ top: 1e9, behavior: "smooth" }); }, [messages, partial]);
  useEffect(() => () => vs.current?.close(), []);

  const openSession = async (id) => {
    setSid(id);
    const d = await api.session(id);
    setMessages((d.messages || []).map((m) => ({ role: m.role, content: m.content, docs: m.docs, tools: [], refused: m.refused })));
  };
  const newSession = () => { setSid(null); setMessages([]); };

  const send = async (text, extra = {}) => {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    let curSid = sid;
    if (!curSid) { const r = await api.newSession(q.slice(0, 40)); curSid = r.id; setSid(curSid); }
    const history = messages.filter((m) => !m.streaming).map((m) => ({ role: m.role, content: m.content }));
    setMessages((m) => [...m, { role: "user", content: q, ...extra },
      { role: "assistant", content: "", tools: [], docs: [], streaming: true }]);
    setInput(""); setBusy(true);

    drip.current.target = "";
    clearInterval(drip.current.timer);
    drip.current.timer = setInterval(() => {
      setMessages((msgs) => {
        const copy = [...msgs]; const last = copy[copy.length - 1];
        if (!last?.streaming) return msgs;
        const tgt = drip.current.target;
        if (last.content.length < tgt.length) {
          last.content = tgt.slice(0, last.content.length + Math.max(2, Math.ceil((tgt.length - last.content.length) / 12)));
          return copy;
        }
        return msgs;
      });
    }, 16);

    chatStream({ query: q, history, channel: "chat", session_id: curSid }, (ev) => {
      setMessages((msgs) => {
        const copy = [...msgs]; const last = copy[copy.length - 1];
        if (ev.type === "tool_call") last.tools = [{ tool: ev.tool, done: false }];
        else if (ev.type === "retrieved") { last.docs = ev.docs || []; last.tools = (last.tools || []).map((t) => ({ ...t, done: true })); }
        else if (ev.type === "token") drip.current.target += ev.text;
        else if (ev.type === "done") {
          drip.current.target = ev.answer || drip.current.target;
          last.refused = ev.refused; last.docs = ev.retrieved || (ev.refused ? [] : last.docs);
          last.tools = (last.tools || []).map((t) => ({ ...t, done: true }));
          setTimeout(() => {
            clearInterval(drip.current.timer);
            setMessages((mm) => { const c = [...mm]; const l = c[c.length - 1]; if (l) { l.content = drip.current.target; l.streaming = false; } return c; });
            setBusy(false); loadSessions();
          }, 300);
        } else if (ev.type === "error") { clearInterval(drip.current.timer); last.content = last.content || "حصل خطأ."; last.streaming = false; setBusy(false); }
        return copy;
      });
    });
  };

  // ---- voice message ----
  // Gemini: NO streaming — record the whole clip, then transcribe it ONCE on stop
  //   (streaming re-transcription of a growing buffer is what caused Gemini to
  //   hallucinate). We wait for that single final before sending to the LLM.
  // QwenCleo: live streaming partials (local, cheap) as before.
  const oneShotAsr = cfg?.asr?.provider === "gemini";
  const voiceAvailable = cfg?.services?.asr || oneShotAsr;
  const toggleRec = async () => {
    if (recording) {
      setRecording(false);
      const s = vs.current;
      if (oneShotAsr) setAnalyzing(true);
      // Wait for the final transcript. One-shot Gemini transcribes on flush, so
      // resolve when onFinal fires (fallback timeout guards against a dropped WS).
      const finalText = await new Promise((resolve) => {
        let done = false;
        const finish = (t) => { if (!done) { done = true; resolve((t || "").trim()); } };
        finalWaiter.current = finish;
        s?.flushASR();
        setTimeout(() => finish(s?.getTranscript() || partialRef.current || ""),
                   oneShotAsr ? 15000 : 1200);
      });
      finalWaiter.current = null;
      const blob = await s?.stopRecording();
      s?.close(); vs.current = null;
      setPartial(""); setAnalyzing(false);
      if (!finalText) { toast("مسمعتش حاجة — جرّب تاني", "warn"); return; }
      send(finalText, { audioUrl: blob && blob.size ? URL.createObjectURL(blob) : null, voice: true });
      return;
    }
    if (!voiceAvailable) { toast("خدمة التعرف على الصوت مش شغّالة", "bad"); return; }
    try {
      const s = createVoiceSession();
      vs.current = s;
      await s.init();
      partialRef.current = "";
      s.resetTranscript();
      s.startASR({
        oneshot: oneShotAsr,
        // In one-shot mode there are no live partials — only the final matters.
        onPartial: (full) => { if (!oneShotAsr) { partialRef.current = full; setPartial(full); } },
        onFinal: (full) => { partialRef.current = full; setPartial(full); finalWaiter.current?.(full); },
      });
      setRecording(true);
    } catch { toast("تعذّر الوصول للميكروفون", "bad"); }
  };
  const partialRef = useRef("");
  const finalWaiter = useRef(null);

  const onAttach = async (files) => {
    for (const f of files) { try { await api.upload(f); toast("تمت إضافة " + f.name + " لقاعدة المعرفة", "ok"); } catch { toast("فشل رفع " + f.name, "bad"); } }
  };

  return (
    <div className={"chat-wrap" + (sessCollapsed ? " sess-collapsed" : "")}>
      <div className="chat-body">
        <aside className="chat-sessions">
          <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
            <button className="btn" style={{ flex: 1 }} onClick={newSession}><Plus size={16} /> محادثة جديدة</button>
            <button className="iconbtn" title="طي المحادثات" onClick={() => setSessCollapsed(true)}><PanelLeftClose size={16} /></button>
          </div>
          {sessions.map((s) => (
            <div key={s.id} className={"sess-item" + (s.id === sid ? " active" : "")} onClick={() => openSession(s.id)}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <MessagesSquare size={13} color="var(--muted)" />
                <div className="t" style={{ flex: 1 }}>{s.title || "محادثة"}</div>
                <button className="row-x" title="حذف" onClick={async (e) => {
                  e.stopPropagation();
                  if (await confirm({ title: "حذف المحادثة", message: `هتتحذف المحادثة «${(s.title || "محادثة").slice(0, 30)}» نهائياً. متأكد؟` })) {
                    await api.delSession(s.id); if (s.id === sid) newSession(); loadSessions();
                  }
                }}><Trash2 size={13} /></button>
              </div>
              <div className="d">{s.n} رسالة</div>
            </div>
          ))}
          {sessions.length === 0 && <div className="hint" style={{ textAlign: "center", marginTop: 20 }}>لا محادثات بعد</div>}
        </aside>
        {sessCollapsed && (
          <button className="sess-expand" title="عرض المحادثات" onClick={() => setSessCollapsed(false)}>
            <PanelLeftOpen size={18} />
          </button>
        )}

        <div className="chat-main">
          <div className="messages" ref={scroller}>
            <div className="msg-col">
              {messages.length === 0 && (
                <div style={{ textAlign: "center", paddingTop: 36 }}>
                  <div style={{ width: 62, height: 62, borderRadius: 18, background: "var(--grad)", color: "var(--on-acc)",
                    display: "grid", placeItems: "center", margin: "0 auto 16px" }}><Bot size={30} /></div>
                  <div style={{ fontSize: 20, fontWeight: 800, color: "var(--ink)" }}>{cfg.agent?.name} جاهز</div>
                  <div className="hint" style={{ fontSize: 14 }}>اسأل عن قاعدة المعرفة — أو جرّب سؤال جاهز</div>
                  <div className="presets">
                    {presets.map((p) => (
                      <button key={p} className="preset" onClick={() => send(p)}>
                        <Sparkles size={13} style={{ marginInlineEnd: 6, color: "var(--acc-3)" }} />{p}
                      </button>))}
                  </div>
                </div>
              )}
              {messages.map((m, i) => <Message key={i} m={m} onPreview={setPreview} toast={toast} voice={cfg?.tts?.active_voice} />)}
              {recording && (
                <div className="msg user">
                  <div className="avatar"><User size={16} /></div>
                  <div className="body">
                    <div className="bubble" style={{ borderColor: "var(--bad)", display: "flex", gap: 9, alignItems: "center" }}>
                      <span className="rec-dot" />
                      {oneShotAsr ? <span style={{ color: "var(--muted)" }}>بسجّل… دوس إيقاف لما تخلص</span>
                        : partial ? partial : <span style={{ color: "var(--muted)" }}>بتكلم… النص بيظهر لحظياً</span>}
                    </div>
                  </div>
                </div>
              )}
              {analyzing && (
                <div className="msg user">
                  <div className="avatar"><User size={16} /></div>
                  <div className="body">
                    <div className="bubble" style={{ display: "flex", gap: 9, alignItems: "center" }}>
                      <Loader2 size={15} className="spin" />
                      <span style={{ color: "var(--muted)" }}>بحلّل صوتك…</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="composer">
            <div className="composer-inner">
              <div className="row">
                <button className={"iconbtn" + (recording ? " rec" : "")} onClick={toggleRec}
                  title={recording ? "إيقاف وإرسال" : "رسالة صوتية"}>
                  {recording ? <Square size={18} /> : <Mic size={18} />}
                </button>
                <label className="iconbtn" title="إرفاق ملف">
                  <Paperclip size={18} />
                  <input type="file" hidden multiple accept=".pdf,.docx,.txt,.md" onChange={(e) => onAttach([...e.target.files])} />
                </label>
                <textarea value={recording ? partial : input} onChange={(e) => setInput(e.target.value)} rows={1}
                  disabled={recording} placeholder={recording ? "بتسجّل…" : "اكتب رسالتك… (Enter للإرسال)"}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
                <button className="iconbtn send" onClick={() => send()} disabled={busy || recording || !input.trim()}><Send size={18} /></button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {preview && (
        <div className="modal-bg" onClick={() => setPreview(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="head"><FileText size={16} />&nbsp;{preview.source}{preview.page ? ` — صفحة ${preview.page}` : ""}
              <div className="spacer" /><X size={18} style={{ cursor: "pointer" }} onClick={() => setPreview(null)} /></div>
            <img src={api.pageUrl(preview.page_image)} alt={preview.source} />
          </div>
        </div>
      )}
    </div>
  );
}

function Message({ m, onPreview, toast, voice }) {
  const isUser = m.role === "user";
  const [loadingTts, setLoadingTts] = useState(false);
  const [openDocs, setOpenDocs] = useState(false);
  const audioRef = useRef(null);

  const speak = async () => {
    if (loadingTts) return;
    setLoadingTts(true);
    try {
      const r = await fetch(api.ttsUrl(), { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: m.content, voice }) });
      if (!r.ok) throw new Error();
      const a = new Audio(URL.createObjectURL(await r.blob()));
      audioRef.current = a; a.play();
    } catch { toast("خدمة تحويل النص لصوت غير متاحة", "bad"); }
    setLoadingTts(false);
  };

  return (
    <div className={"msg " + (isUser ? "user" : "bot") + (m.refused ? " refused" : "")}>
      <div className="avatar">{isUser ? <User size={16} /> : <Bot size={16} />}</div>
      <div className="body">
        {!isUser && m.tools?.length > 0 && (
          <div>{m.tools.map((t, i) => (
            <span key={i} className="tool-chip">
              {t.done ? <CheckCircle2 size={13} /> : <Search size={13} className="spin" />}
              {t.tool === "retrieve_kb" ? "البحث في قاعدة المعرفة" : t.tool}{t.done ? " ✓" : "…"}
            </span>))}
          </div>
        )}
        {m.voice && <span className="pill grad" style={{ marginBottom: 6 }}><AudioLines size={11} /> رسالة صوتية</span>}
        <div className={"bubble" + (m.streaming ? " cursor-blink" : "")}>{m.content}</div>
        {m.audioUrl && <div style={{ marginTop: 8 }}><AudioPlayer src={m.audioUrl} compact /></div>}

        {!isUser && !m.streaming && m.content && (
          <button className="btn ghost sm" style={{ marginTop: 8 }} onClick={speak} disabled={loadingTts}>
            {loadingTts ? <><Loader2 size={14} className="spin" /> جاري التوليد…</> : <><Volume2 size={14} /> استمع</>}
          </button>
        )}

        {m.docs?.length > 0 && !m.refused && (
          <div style={{ marginTop: 10 }}>
            <button className="expander" onClick={() => setOpenDocs((v) => !v)}>
              <ChevronDown size={15} style={{ transform: openDocs ? "rotate(180deg)" : "none", transition: "transform .2s" }} />
              المصادر ({m.docs.length})
            </button>
            <AnimatePresence initial={false}>
              {openDocs && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }} transition={{ duration: .22 }} style={{ overflow: "hidden" }}>
                  <div className="docs">
                    {m.docs.map((d, i) => (
                      <div key={i} className="doc-card" onClick={() => d.page_image && onPreview(d)}>
                        <div className="thumb">{d.page_image ? <img src={api.pageUrl(d.page_image)} alt={d.source} /> : <FileText size={28} color="var(--muted)" />}</div>
                        <div className="meta">
                          <div className="src">{d.source}</div>
                          <div className="score" style={{ marginTop: 5 }}>{matchBadge(d.score)}</div>
                        </div>
                      </div>))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
      </div>
    </div>
  );
}
