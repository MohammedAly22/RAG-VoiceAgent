import React, { useEffect, useState } from "react";
import { ArrowRight, Bot, User, Clock, Phone, MessagesSquare, FileText, Ban,
         CheckCircle2, Wrench, Search, Cpu, Zap, Trash2 } from "lucide-react";
import { api, TYPE_AR, CHANNEL_AR } from "../lib/api.js";
import AudioPlayer from "../components/AudioPlayer.jsx";
import { useConfirm } from "../components/Confirm.jsx";

/* Relevance label: strong / moderate / weak — colour-coded. */
export function matchBadge(score) {
  const p = Math.round((score || 0) * 100);
  if (p >= 70) return <span className="pill ok">تطابق قوي {p}%</span>;
  if (p >= 45) return <span className="pill warn">تطابق متوسط {p}%</span>;
  return <span className="pill bad">تطابق ضعيف {p}%</span>;
}

const Back = ({ go, to, label }) => (
  <button className="back-btn" onClick={() => go(to)}><ArrowRight size={16} /> {label}</button>
);
const fmt = (t) => t ? new Date(t * 1000).toLocaleString("ar-EG",
  { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
const dur = (s) => s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : "0:00";

/* ============================== session page ============================== */
export function SessionPage({ id, go }) {
  const [d, setD] = useState(null);
  const confirm = useConfirm();
  useEffect(() => { id && api.session(id).then(setD).catch(() => setD({ session: {}, messages: [] })); }, [id]);
  if (!d) return <div className="empty">جاري التحميل…</div>;
  return (
    <div className="page">
      <Back go={go} to="dashboard" label="رجوع للوحة التحكم" />
      <div className="card" style={{ marginTop: 12 }}>
        <div className="card-head"><MessagesSquare size={17} /> {d.session?.title || "محادثة"}
          <div className="spacer" />
          <span className="pill">{(d.messages || []).length} رسالة</span>
          <span className="pill">{fmt(d.session?.created_at)}</span>
          <button className="iconbtn sm danger" title="حذف"
            onClick={async () => { if (await confirm({ title: "حذف المحادثة", message: "هتتحذف المحادثة نهائياً. متأكد؟" })) api.delSession(id).then(() => go("dashboard")); }}><Trash2 size={14} /></button>
        </div>
        <div className="card-body">
          {(d.messages || []).map((m) => (
            <div key={m.id} className={"msg " + (m.role === "user" ? "user" : "bot") + (m.refused ? " refused" : "")}
              style={{ marginBottom: 16 }}>
              <div className="avatar">{m.role === "user" ? <User size={16} /> : <Bot size={16} />}</div>
              <div className="body">
                <div className="bubble">{m.content}</div>
                {m.refused && <span className="pill bad" style={{ marginTop: 7 }}><Ban size={11} /> رفض</span>}
                {m.docs?.length > 0 && (
                  <div className="docs">
                    {m.docs.map((x, i) => (
                      <div key={i} className="doc-card">
                        <div className="thumb">{x.page_image
                          ? <img src={api.pageUrl(x.page_image)} alt={x.source} />
                          : <FileText size={28} color="var(--muted)" />}</div>
                        <div className="meta"><div className="src">{x.source}</div>
                          <div className="score">{TYPE_AR[x.type] || x.type}{x.page ? ` · ص${x.page}` : ""}</div></div>
                      </div>))}
                  </div>)}
              </div>
            </div>))}
          {(d.messages || []).length === 0 && <div className="empty">لا رسائل</div>}
        </div>
      </div>
    </div>
  );
}

/* ================================ call page =============================== */
export function CallPage({ id, go }) {
  const [c, setC] = useState(null);
  const confirm = useConfirm();
  useEffect(() => { id && api.call(id).then(setC).catch(() => setC(null)); }, [id]);
  if (!c) return <div className="empty">جاري التحميل…</div>;
  return (
    <div className="page">
      <Back go={go} to="dashboard" label="رجوع للوحة التحكم" />
      <div className="stat-grid" style={{ margin: "12px 0 18px" }}>
        <div className="stat"><div className="ic"><Clock size={18} /></div><div className="v">{dur(c.duration_sec)}</div><div className="l">مدة المكالمة</div></div>
        <div className="stat"><div className="ic"><MessagesSquare size={18} /></div><div className="v">{c.turns}</div><div className="l">عدد التبادلات</div></div>
        <div className="stat"><div className="ic"><Phone size={18} /></div><div className="v" style={{ fontSize: 18 }}>{c.outcome}</div><div className="l">النتيجة</div></div>
      </div>
      {c.has_audio && (
        <div className="card" style={{ marginBottom: 18 }}>
          <div className="card-head"><Zap size={16} /> التسجيل الصوتي</div>
          <div className="card-body">
            <AudioPlayer src={api.callAudioUrl(c.id)} label="تسجيل المكالمة (صوتك + صوت الوكيل)" />
          </div>
        </div>)}
      <div className="card">
        <div className="card-head"><FileText size={16} /> نص المكالمة
          <div className="spacer" /><span className="pill">{fmt(c.created_at)}</span>
          <button className="iconbtn sm danger" onClick={async () => { if (await confirm({ title: "حذف المكالمة", message: "هتتحذف المكالمة وتسجيلها نهائياً. متأكد؟" })) api.delCall(id).then(() => go("dashboard")); }}><Trash2 size={14} /></button>
        </div>
        <div className="card-body">
          {(c.transcript || []).map((t, i) => (
            <div key={i} className={"msg " + (t.role === "user" ? "user" : "bot")} style={{ marginBottom: 14 }}>
              <div className="avatar">{t.role === "user" ? <User size={16} /> : <Bot size={16} />}</div>
              <div className="body"><div className="bubble">{t.text}</div></div>
            </div>))}
          {(c.transcript || []).length === 0 && <div className="empty">لا يوجد نص</div>}
        </div>
      </div>
    </div>
  );
}

/* ================================ log page ================================ */
export function LogPage({ id, go }) {
  const [l, setL] = useState(null);
  useEffect(() => { id && api.log(id).then(setL).catch(() => setL(null)); }, [id]);
  if (!l) return <div className="empty">جاري التحميل…</div>;
  const evColor = (e) => e.type === "tool_call" ? "tool" : e.type === "no_context" ? "bad" : "info";
  return (
    <div className="page">
      <Back go={go} to="logs" label="رجوع للسجلات" />

      <div className="stat-grid" style={{ margin: "12px 0 18px" }}>
        <div className="stat"><div className="ic"><Cpu size={18} /></div><div className="v" style={{ fontSize: 18 }}>{l.backend}</div><div className="l">النموذج</div></div>
        <div className="stat"><div className="ic"><Zap size={18} /></div><div className="v">{l.first_token_ms ?? "—"}<span style={{ fontSize: 14 }}>ms</span></div><div className="l">زمن أول رمز (TTFT)</div></div>
        <div className="stat"><div className="ic"><Clock size={18} /></div><div className="v">{l.total_ms ?? "—"}<span style={{ fontSize: 14 }}>ms</span></div><div className="l">الزمن الكلي</div></div>
        <div className="stat"><div className="ic">{l.refused ? <Ban size={18} /> : <CheckCircle2 size={18} />}</div>
          <div className="v" style={{ fontSize: 18 }}>{l.refused ? "رفض" : "تم الرد"}</div><div className="l">الحالة</div></div>
      </div>

      <div className="grid2" style={{ marginBottom: 18 }}>
        <div className="card"><div className="card-head"><User size={16} /> السؤال</div>
          <div className="card-body" style={{ lineHeight: 1.9, color: "var(--ink)" }}>{l.query}</div></div>
        <div className="card"><div className="card-head"><Bot size={16} /> الرد</div>
          <div className="card-body" style={{ lineHeight: 1.9, color: "var(--ink)" }}>{l.answer || "—"}</div></div>
      </div>

      <div className="card" style={{ marginBottom: 18 }}>
        <div className="card-head"><Wrench size={16} /> استدعاءات الأدوات ومسار التنفيذ</div>
        <div className="card-body">
          {(l.events || []).length === 0 && <div className="hint" style={{ margin: 0 }}>لم يتم استدعاء أي أداة (رد مباشر من شخصية الوكيل)</div>}
          {(l.events || []).map((e, i) => (
            <div key={i} style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "11px 13px",
              borderRadius: 11, background: "var(--tool-bg)", marginBottom: 8,
              borderInlineStart: "3px solid var(--tool)" }}>
              <span className={"pill " + evColor(e)} style={{ flex: "none" }}>
                {e.type === "tool_call" ? <Wrench size={11} /> : <Search size={11} />}
                {e.type === "tool_call" ? (e.tool || "tool") : e.type}
              </span>
              <div className="mono" style={{ flex: 1, color: "var(--ink-2)", wordBreak: "break-all" }}>
                {JSON.stringify(e)}
              </div>
            </div>))}
        </div>
      </div>

      <div className="card">
        <div className="card-head"><Search size={16} /> المقاطع المسترجعة
          <div className="spacer" /><span className="pill">{(l.retrieved || []).length}</span></div>
        <div className="card-body">
          {(l.retrieved || []).length === 0 && <div className="hint" style={{ margin: 0 }}>لا مقاطع (لم يتم البحث في قاعدة المعرفة)</div>}
          {(l.retrieved || []).map((d, i) => (
            <div key={i} className="viewer-chunk">
              <div style={{ display: "flex", gap: 8, marginBottom: 8, flexWrap: "wrap", alignItems: "center" }}>
                <span className="pill grad">{d.source}{d.page ? ` · ص${d.page}` : ""}</span>
                <span className="pill">{TYPE_AR[d.type] || d.type}</span>
                {matchBadge(d.score)}
              </div>
              <div style={{ fontSize: 13.5, lineHeight: 1.85 }}>{d.text || d.snippet}</div>
            </div>))}
        </div>
      </div>
    </div>
  );
}
