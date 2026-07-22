import React, { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, MicOff, PhoneOff, Hand } from "lucide-react";
import VoiceOrb from "../components/VoiceOrb.jsx";
import { api, chatStream } from "../lib/api.js";
import { createVoiceSession } from "../lib/voice.js";

// Full-screen live call.
//  • ASR is VAD-gated and accumulates partials, so text appears as you speak and
//    silence is never sent (the recognizer used to hallucinate on silence).
//  • While the agent talks the mic keeps listening for a barge-in: start talking
//    and the agent is cut off mid-sentence and listens to you instead.
//  • The recording mixes both voices; the page follows the light/dark theme.
export default function VoiceCall({ cfg, onClose }) {
  const [state, setState] = useState("connecting");   // connecting|live|ended
  const [speaking, setSpeaking] = useState("idle");   // idle|user|thinking|agent
  const [muted, setMuted] = useState(false);
  const [micLevel, setMicLevel] = useState(0);
  const [agentLvl, setAgentLvl] = useState(0);
  const [live, setLive] = useState("");               // live transcript of this turn
  const [lastAnswer, setLastAnswer] = useState("");
  const [interrupted, setInterrupted] = useState(false);
  const [err, setErr] = useState("");
  const [secs, setSecs] = useState(0);

  const name = cfg?.agent?.name || "المساعد";
  const vs = useRef(null);
  const raf = useRef(0);
  const transcript = useRef([]);
  const st = useRef({ busy: false, history: [], t0: Date.now(), turnId: 0 });

  useEffect(() => { start(); return () => vs.current?.close(); }, []);
  useEffect(() => {
    const t = setInterval(() => setSecs(Math.floor((Date.now() - st.current.t0) / 1000)), 1000);
    return () => clearInterval(t);
  }, []);

  const start = async () => {
    if (!cfg?.services?.asr || !cfg?.services?.tts)
      setErr("خدمة الصوت (ASR/TTS) مش شغّالة — شغّل: scripts/start_all.sh voice");
    try {
      const s = createVoiceSession();
      vs.current = s;
      await s.init();
      s.startASR({
        onSpeechStart: () => { if (!st.current.busy) setSpeaking("user"); },
        onPartial: (full) => { if (!st.current.busy) { setLive(full); setSpeaking("user"); } },
        onFinal: (full) => { const t = (full || "").trim(); if (t && !st.current.busy) handleUtterance(t); },
        onLevel: (l) => setMicLevel(st.current.busy ? 0 : l),
        onBargeIn: () => bargeIn(),
      });
      const tick = () => { setAgentLvl(s.agentLevel()); raf.current = requestAnimationFrame(tick); };
      tick();
      setState("live");
    } catch { setErr("تعذّر الوصول للميكروفون."); setState("live"); }
  };

  // User started talking over the agent → cut the agent off and listen.
  const bargeIn = () => {
    if (!vs.current?.isSpeaking()) return;
    st.current.turnId++;              // invalidates the in-flight turn
    vs.current.stopSpeaking();
    st.current.busy = false;
    vs.current.resetTranscript();
    setInterrupted(true); setTimeout(() => setInterrupted(false), 1600);
    setSpeaking("user"); setLive("");
  };

  const handleUtterance = async (text) => {
    if (st.current.busy || !text) return;
    const turn = ++st.current.turnId;
    st.current.busy = true;
    vs.current?.resetTranscript();
    setLive(""); setSpeaking("thinking"); setMicLevel(0);
    transcript.current.push({ role: "user", text, t: secs });
    try {
      const answer = await respond(text, turn);       // resolves after audio finishes
      if (turn === st.current.turnId && answer)
        transcript.current.push({ role: "assistant", text: answer, t: secs });
    } catch (e) { setErr("خطأ: " + (e.message || e)); }
    if (turn === st.current.turnId) {
      st.current.busy = false;
      vs.current?.resetTranscript();
      setSpeaking("idle");
    }
  };

  // Stream the LLM answer and speak it SENTENCE BY SENTENCE as it's produced, so
  // the first audio plays while the model is still generating (low latency). The
  // sentences are chained so they always play in order; barge-in cancels the lot.
  const respond = (q, turn) => new Promise((resolve) => {
    const voice = cfg?.tts?.active_voice;
    const s = vs.current;
    let acc = "", buf = "", spoke = false, chain = Promise.resolve();
    s?.beginSpeaking();

    const enqueue = (sentence) => {
      const t = (sentence || "").trim();
      if (!t) return;
      if (!spoke) { spoke = true; setSpeaking("agent"); }
      chain = chain.then(() => (turn === st.current.turnId ? s?.speak(t, voice) : null));
    };
    const flush = (all) => {
      if (all) { enqueue(buf); buf = ""; return; }
      let last = -1, m; const enders = /[.!؟?\n]/g;
      while ((m = enders.exec(buf))) last = m.index;
      if (last >= 0) { enqueue(buf.slice(0, last + 1)); buf = buf.slice(last + 1); }
      else if (buf.length > 90) {                       // long clause, no ender yet
        const sp = buf.lastIndexOf(" ", 90);
        if (sp > 0) { enqueue(buf.slice(0, sp)); buf = buf.slice(sp + 1); }
      }
    };

    chatStream({ query: q, history: st.current.history, channel: "voice" }, (ev) => {
      if (turn !== st.current.turnId) { s?.endSpeaking(); return resolve(acc); }
      if (ev.type === "token") { acc += ev.text; buf += ev.text; setLastAnswer(acc); flush(false); }
      else if (ev.type === "done") {
        const a = ev.answer || acc;
        st.current.history.push({ role: "user", content: q }, { role: "assistant", content: a });
        flush(true);
        chain.then(() => { if (turn === st.current.turnId) s?.endSpeaking(); resolve(a); });
      } else if (ev.type === "error") {
        flush(true);
        chain.then(() => { s?.endSpeaking(); resolve(acc || "معلش، حصل خطأ."); });
      }
    });
  });

  const hangup = async () => {
    setState("ended");
    cancelAnimationFrame(raf.current);
    vs.current?.stopSpeaking();
    const blob = await vs.current?.stopRecording();
    vs.current?.close();
    if (transcript.current.length) {
      try {
        const first = transcript.current.find((t) => t.role === "user");
        const { id } = await api.newCall({
          title: first ? first.text.slice(0, 40) : "مكالمة صوتية",
          transcript: transcript.current, duration_sec: secs,
          summary: transcript.current.filter((t) => t.role === "assistant").slice(-1)[0]?.text?.slice(0, 120) || "",
        });
        if (blob && blob.size) await api.uploadCallAudio(id, blob);
      } catch { /* ignore */ }
    }
    onClose();
  };

  const caption = state === "connecting" ? "جاري التوصيل…"
    : interrupted ? "اتفضل، بسمعك…"
    : speaking === "agent" ? `${name} بيتكلم…`
    : speaking === "thinking" ? `${name} بيفكر…`
    : speaking === "user" ? "بسمعك…" : "اتكلم دلوقتي — المساعد بيستمع";
  const mm = String(Math.floor(secs / 60)).padStart(2, "0"), ss = String(secs % 60).padStart(2, "0");
  const sub = live ? `أنت: ${live}` : lastAnswer;

  return (
    <motion.div className="voicecall" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <div className="vc-bg" />
      <div className="vc-timer">{mm}:{ss}</div>
      <div className="vc-live"><span className="rd" /> مباشر</div>
      <div className="vc-center">
        <VoiceOrb micLevel={micLevel} agentLevel={agentLvl} speaking={speaking} size={300} />
        <AnimatePresence mode="wait">
          <motion.div key={caption} className="vc-caption" initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>{caption}</motion.div>
        </AnimatePresence>
        {sub && <div className="vc-subtitle">{sub}</div>}
        {err && <div className="vc-err">{err}</div>}
      </div>
      <div className="vc-hint"><Hand size={12} style={{ verticalAlign: "-2px" }} /> تقدر تقاطع المساعد وهو بيتكلم — اتكلم وهيسكت</div>
      <div className="vc-controls">
        <button className={`vc-btn mic ${muted ? "muted" : ""}`}
          onClick={() => { const m = !muted; setMuted(m); vs.current?.setMuted(m); }} title="كتم">
          {muted ? <MicOff size={22} /> : <Mic size={22} />}
        </button>
        <button className="vc-btn end" onClick={hangup} title="إنهاء المكالمة"><PhoneOff size={22} /></button>
      </div>
    </motion.div>
  );
}
