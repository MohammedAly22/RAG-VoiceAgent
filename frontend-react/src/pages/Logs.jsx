import React, { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { RefreshCw, Search, X, Ban, CheckCircle2, ChevronLeft, ChevronRight,
         Activity, Zap, Clock } from "lucide-react";
import { api, CHANNEL_AR } from "../lib/api.js";

const PER_PAGE = 8;
const FILTERS = [
  { id: "all", label: "الكل" }, { id: "answered", label: "تم الرد" },
  { id: "refused", label: "مرفوضة" }, { id: "voice", label: "صوت" }, { id: "chat", label: "دردشة" },
];

export default function Logs({ go }) {
  const [logs, setLogs] = useState([]);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(1);

  const load = () => api.logs().then((r) => setLogs(r.logs || [])).catch(() => {});
  useEffect(() => { load(); }, []);
  useEffect(() => { setPage(1); }, [q, filter]);

  const filtered = useMemo(() => logs.filter((l) => {
    if (q && !((l.query || "") + (l.answer || "")).includes(q)) return false;
    if (filter === "answered") return !l.refused;
    if (filter === "refused") return l.refused;
    if (filter === "voice") return l.channel === "voice";
    if (filter === "chat") return l.channel === "chat";
    return true;
  }), [logs, q, filter]);

  const pages = Math.max(1, Math.ceil(filtered.length / PER_PAGE));
  const cur = filtered.slice((page - 1) * PER_PAGE, page * PER_PAGE);

  return (
    <div className="page">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <div>
          <h3 style={{ margin: 0, color: "var(--ink)" }}>سجل الاستعلامات</h3>
          <div className="hint" style={{ margin: 0 }}>تتبّع تفصيلي لكل رد: الأدوات، المقاطع المسترجعة، التوقيتات.</div>
        </div>
        <div className="spacer" />
        <button className="btn ghost sm" onClick={load}><RefreshCw size={14} /> تحديث</button>
      </div>

      <div className="search-bar" style={{ marginBottom: 14 }}>
        <Search size={18} color="var(--muted)" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="ابحث في الأسئلة والردود…" />
        {q && <X size={16} style={{ cursor: "pointer", color: "var(--muted)" }} onClick={() => setQ("")} />}
      </div>

      <div className="filter-chips">
        {FILTERS.map((f) => (
          <button key={f.id} className={"chip" + (filter === f.id ? " on" : "")} onClick={() => setFilter(f.id)}>
            {f.label}
          </button>
        ))}
        <div className="spacer" />
        <span className="pill">{filtered.length} نتيجة</span>
      </div>

      <div className="card">
        <div className="card-body" style={{ padding: 14 }}>
          {cur.length === 0 && <div className="empty" style={{ padding: 34 }}>لا سجلات مطابقة</div>}
          {cur.map((l, i) => (
            <motion.div key={l.id} className="list-row" onClick={() => go("log", l.id)}
              initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}>
              <div className="ic" style={{ background: l.refused ? "var(--bad-bg)" : "var(--ok-bg)",
                color: l.refused ? "var(--bad)" : "var(--ok)" }}>
                {l.refused ? <Ban size={16} /> : <CheckCircle2 size={16} />}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 14, color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.query}</div>
                <div style={{ fontSize: 12, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.answer || "—"}</div>
              </div>
              <span className="pill">{CHANNEL_AR[l.channel] || l.channel}</span>
              <span className="pill info" title="زمن أول رمز"><Zap size={11} /> {l.first_token_ms ?? "—"}ms</span>
              <span className="pill" title="الزمن الكلي"><Clock size={11} /> {l.total_ms ? (l.total_ms / 1000).toFixed(1) + "s" : "—"}</span>
              <ChevronLeft size={16} color="var(--faint)" />
            </motion.div>
          ))}
        </div>
      </div>

      {pages > 1 && (
        <div className="pager">
          <button disabled={page === 1} onClick={() => setPage((p) => p - 1)}><ChevronRight size={15} /></button>
          {Array.from({ length: pages }, (_, i) => i + 1)
            .filter((p) => p === 1 || p === pages || Math.abs(p - page) <= 1)
            .map((p, idx, arr) => (
              <React.Fragment key={p}>
                {idx > 0 && arr[idx - 1] !== p - 1 && <span style={{ color: "var(--faint)" }}>…</span>}
                <button className={p === page ? "on" : ""} onClick={() => setPage(p)}>{p}</button>
              </React.Fragment>
            ))}
          <button disabled={page === pages} onClick={() => setPage((p) => p + 1)}><ChevronLeft size={15} /></button>
        </div>
      )}
    </div>
  );
}
