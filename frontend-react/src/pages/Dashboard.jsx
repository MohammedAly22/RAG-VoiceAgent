import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { MessagesSquare, Phone, Database, Layers, Clock, Trash2, PlayCircle,
         Plus, ChevronLeft, Activity } from "lucide-react";
import { api, CHANNEL_AR } from "../lib/api.js";
import { useConfirm } from "../components/Confirm.jsx";
import { SkelStats, SkelRows } from "../components/Skeleton.jsx";

export default function Dashboard({ go, goCall }) {
  const confirm = useConfirm();
  const [stats, setStats] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [calls, setCalls] = useState([]);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = () => Promise.all([api.stats(), api.sessions(), api.calls(), api.logs()])
    .then(([s, se, c, l]) => { setStats(s); setSessions(se.sessions || []); setCalls(c.calls || []); setLogs((l.logs || []).slice(0, 6)); })
    .catch(() => {})
    .finally(() => setLoading(false));
  useEffect(() => { load(); }, []);

  const fmt = (t) => t ? new Date(t * 1000).toLocaleString("ar-EG", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
  const dur = (s) => s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : "0:00";

  const tiles = [
    { l: "المحادثات", v: stats?.sessions ?? "—", ic: <MessagesSquare size={19} /> },
    { l: "المكالمات", v: stats?.calls ?? "—", ic: <Phone size={19} /> },
    { l: "المستندات", v: stats?.kb_docs ?? "—", ic: <Database size={19} /> },
    { l: "المقاطع المفهرسة", v: stats?.kb_chunks ?? "—", ic: <Layers size={19} /> },
  ];

  return (
    <div className="page">
      {loading ? <SkelStats /> : (
        <div className="stat-grid" style={{ marginBottom: 20 }}>
          {tiles.map((t, i) => (
            <motion.div key={t.l} className="stat" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.06 }}>
              <div className="ic">{t.ic}</div>
              <div className="v">{t.v}</div>
              <div className="l">{t.l}</div>
            </motion.div>
          ))}
        </div>
      )}

      <div className="grid2" style={{ marginBottom: 18 }}>
        <Panel title="المحادثات الأخيرة" icon={<MessagesSquare size={17} />}
          action={<button className="btn sm" onClick={() => go("chat")}><Plus size={14} /> دردشة جديدة</button>}>
          {loading && <SkelRows n={4} />}
          {!loading && sessions.length === 0 && <div className="empty" style={{ padding: 28 }}>لا محادثات بعد</div>}
          {!loading && sessions.slice(0, 6).map((s, i) => (
            <motion.div key={s.id} className="list-row"
              initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} onClick={() => go("session", s.id)}>
              <div className="ic" style={{ background: "var(--acc-soft)", color: "var(--acc-3)" }}><MessagesSquare size={16} /></div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 14, color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.title || "محادثة"}</div>
                <div style={{ fontSize: 12, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.last || "—"}</div>
              </div>
              <span className="pill">{s.n} رسالة</span>
              <button className="iconbtn sm danger" onClick={async (e) => { e.stopPropagation(); if (await confirm({ title: "حذف المحادثة", message: "هتتحذف المحادثة نهائياً. متأكد؟" })) api.delSession(s.id).then(load); }}><Trash2 size={13} /></button>
              <ChevronLeft size={16} color="var(--faint)" />
            </motion.div>
          ))}
        </Panel>

        <Panel title="المكالمات الأخيرة" icon={<Phone size={17} />}
          action={<button className="btn sm" onClick={goCall}><Phone size={14} /> مكالمة جديدة</button>}>
          {loading && <SkelRows n={4} />}
          {!loading && calls.length === 0 && <div className="empty" style={{ padding: 28 }}>لا مكالمات بعد</div>}
          {!loading && calls.slice(0, 6).map((c, i) => (
            <motion.div key={c.id} className="list-row"
              initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} onClick={() => go("call", c.id)}>
              <div className="ic" style={{ background: "var(--grad)", color: "var(--on-acc)" }}><Phone size={15} /></div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 14, color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.title}</div>
                <div style={{ fontSize: 12, color: "var(--muted)" }}>{fmt(c.created_at)} · {c.turns} تبادل</div>
              </div>
              {c.has_audio && <span className="pill grad"><PlayCircle size={11} /> تسجيل</span>}
              <span className="pill"><Clock size={11} /> {dur(c.duration_sec)}</span>
              <button className="iconbtn sm danger" onClick={async (e) => { e.stopPropagation(); if (await confirm({ title: "حذف المكالمة", message: "هتتحذف المكالمة وتسجيلها نهائياً. متأكد؟" })) api.delCall(c.id).then(load); }}><Trash2 size={13} /></button>
            </motion.div>
          ))}
        </Panel>
      </div>

      <Panel title="أحدث نشاط الوكيل" icon={<Activity size={17} />}
        action={<button className="btn ghost sm" onClick={() => go("logs")}>كل السجلات</button>}>
        {loading && <SkelRows n={3} />}
        {!loading && logs.length === 0 && <div className="empty" style={{ padding: 26 }}>لا سجلات بعد</div>}
        {!loading && logs.map((l, i) => (
          <motion.div key={l.id} className="list-row"
            initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} onClick={() => go("log", l.id)}>
            <div className="ic" style={{ background: l.refused ? "var(--bad-bg)" : "var(--ok-bg)", color: l.refused ? "var(--bad)" : "var(--ok)" }}>
              <Activity size={15} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 13.5, color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.query}</div>
              <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{CHANNEL_AR[l.channel] || l.channel} · {l.ts?.replace("T", " ").slice(0, 16)}</div>
            </div>
            <span className="pill">{l.first_token_ms ?? "—"}ms</span>
            {l.refused ? <span className="pill bad">رفض</span> : <span className="pill ok">تم الرد</span>}
          </motion.div>
        ))}
      </Panel>
    </div>
  );
}

const Panel = ({ title, icon, action, children }) => (
  <div className="card">
    <div className="card-head">{icon} {title}<div className="spacer" />{action}</div>
    <div className="card-body">{children}</div>
  </div>
);
