import React, { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Upload, Trash2, RefreshCw, FileText, Loader2, Table, Image as Img,
         Search, Eye, X, FileType2, Filter } from "lucide-react";
import { api, TYPE_AR } from "../lib/api.js";
import { useToast } from "../components/Toast.jsx";
import { useConfirm } from "../components/Confirm.jsx";

const KINDS = [
  { id: "all", label: "الكل" }, { id: "pdf", label: "PDF" },
  { id: "docx", label: "DOCX" }, { id: "text", label: "نصوص" }, { id: "image", label: "صور" },
];
const kindOf = (s) => s.endsWith(".pdf") ? "pdf" : s.endsWith(".docx") ? "docx"
  : /\.(png|jpe?g|gif|webp)$/i.test(s) ? "image" : "text";

export default function DataTab() {
  const [sources, setSources] = useState([]);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const [q, setQ] = useState("");
  const [results, setResults] = useState(null);
  const [filter, setFilter] = useState("all");
  const [viewer, setViewer] = useState(null);
  const inp = useRef(); const tmr = useRef();
  const toast = useToast();
  const confirm = useConfirm();

  const load = () => api.data().then((r) => { setSources(r.sources || []); setTotal(r.total_chunks || 0); });
  useEffect(() => { load(); }, []);

  const upload = async (files) => {
    setBusy(true);
    for (const f of files) { try { await api.upload(f); toast("تمت إضافة " + f.name, "ok"); } catch (e) { toast("فشل رفع " + f.name, "bad"); } }
    await load(); setBusy(false);
  };
  const remove = async (s) => {
    if (!await confirm({ title: "حذف مستند", message: `هيتحذف «${s}» من قاعدة المعرفة نهائياً. متأكد؟` })) return;
    await api.removeSource(s); toast("تم الحذف", "ok"); load();
  };
  const onSearch = (v) => { setQ(v); clearTimeout(tmr.current); if (!v.trim()) { setResults(null); return; }
    tmr.current = setTimeout(async () => { try { setResults((await api.search(v)).results || []); } catch { setResults([]); } }, 280); };

  const shown = sources.filter((s) => filter === "all" || kindOf(s.source) === filter);

  return (
    <div style={{ maxWidth: 1080, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 16 }}>
        <div><h3 style={{ margin: 0 }}>قاعدة المعرفة</h3>
          <div className="hint" style={{ margin: 0 }}>{sources.length} مستند · {total} مقطع مفهرس في FAISS</div></div>
        <div style={{ flex: 1 }} />
        <button className="btn ghost sm" onClick={() => api.reindex().then(load)}><RefreshCw size={14} /> إعادة فهرسة</button>
      </div>

      <div className="search-bar" style={{ marginBottom: 22 }}>
        <Search size={18} color="var(--muted)" />
        <input value={q} onChange={(e) => onSearch(e.target.value)} placeholder="ابحث في قاعدة المعرفة (بحث دلالي)…" />
        {q && <X size={16} style={{ cursor: "pointer", color: "var(--muted)" }} onClick={() => onSearch("")} />}
      </div>

      {results && (
        <div style={{ marginBottom: 18 }}>
          <div className="hint" style={{ marginTop: 0 }}>{results.length} نتيجة</div>
          {results.map((r, i) => (
            <motion.div key={i} className="search-res" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }} onClick={() => setViewer(r.source)}>
              <div style={{ display: "flex", gap: 8, marginBottom: 5, alignItems: "center", flexWrap: "wrap" }}>
                <span className="pill">{r.source}{r.page ? ` · ص${r.page}` : ""}</span>
                <span className="pill">{TYPE_AR[r.type] || r.type}</span>
                <span className="pill grad">تطابق {(r.score * 100).toFixed(0)}%</span>
              </div>
              <div style={{ fontSize: 13.5, color: "var(--ink-2)", lineHeight: 1.8 }}>{r.snippet}…</div>
            </motion.div>
          ))}
        </div>
      )}

      <div className={"dropzone" + (drag ? " drag" : "")} style={{ marginBottom: 22, marginTop: 6 }}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); upload([...e.dataTransfer.files]); }} onClick={() => inp.current?.click()}>
        {busy ? <Loader2 className="spin" size={22} /> : <Upload size={22} />}
        <div style={{ marginTop: 8, fontWeight: 600 }}>{busy ? "جاري الرفع والفهرسة…" : "اسحب ملفات (PDF / DOCX / TXT / MD) أو اضغط للاختيار"}</div>
        <div className="hint">يدعم النص والجداول والصور (multimodal)</div>
        <input ref={inp} type="file" hidden multiple accept=".pdf,.docx,.txt,.md" onChange={(e) => upload([...e.target.files])} />
      </div>

      <div className="filter-chips">
        <Filter size={16} color="var(--muted)" style={{ alignSelf: "center" }} />
        {KINDS.map((k) => <button key={k.id} className={"chip" + (filter === k.id ? " on" : "")} onClick={() => setFilter(k.id)}>{k.label}</button>)}
      </div>

      <div className="data-grid">
        {shown.length === 0 && <div className="empty" style={{ gridColumn: "1/-1" }}>لا توجد بيانات{filter !== "all" ? " من هذا النوع" : " بعد"}</div>}
        {shown.map((s) => {
          const kind = kindOf(s.source);
          const thumb = kind === "pdf" ? api.pageUrl(`${s.source}/p1.png`) : kind === "image" ? api.sourceFileUrl(s.source) : null;
          return (
            <motion.div key={s.source} className="file-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <div className="fc-thumb">
                {thumb ? <img src={thumb} alt={s.source} onError={(e) => { e.target.style.display = "none"; }} />
                  : (kind === "docx" ? <FileType2 size={40} color="var(--muted)" /> : <FileText size={40} color="var(--muted)" />)}
                <span className="fc-kind pill grad">{kind.toUpperCase()}</span>
              </div>
              <div className="fc-body">
                <div className="fc-name">{s.source}</div>
                <div className="fc-meta">{s.chunks} مقطع{s.pages ? ` · ${s.pages} صفحة` : ""}</div>
                <div style={{ display: "flex", gap: 5, marginTop: 8, flexWrap: "wrap" }}>
                  {(s.types || []).map((t) => <span key={t} className="pill" style={{ gap: 4 }}>{t === "table" ? <Table size={11} /> : t === "image_caption" ? <Img size={11} /> : <FileText size={11} />}{TYPE_AR[t] || t}</span>)}
                </div>
                <div className="fc-actions">
                  <button className="btn ghost sm" style={{ flex: 1 }} onClick={() => setViewer(s.source)}><Eye size={14} /> معاينة</button>
                  <button className="iconbtn" style={{ width: 34, height: 34 }} onClick={() => remove(s.source)}><Trash2 size={14} /></button>
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>

      {viewer && <FileViewer source={viewer} onClose={() => setViewer(null)} />}
    </div>
  );
}

function FileViewer({ source, onClose }) {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  useEffect(() => { api.sourceChunks(source).then(setData).catch(() => setData({ chunks: [], pages: [], kind: "text" })); }, [source]);
  const kind = data?.kind;
  const chunks = (data?.chunks || []).filter((c) => !q || (c.text || "").includes(q));

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" style={{ width: 820, maxWidth: "94vw" }} onClick={(e) => e.stopPropagation()}>
        <div className="head"><FileText size={16} />&nbsp;{source}<div style={{ flex: 1 }} />
          <a className="btn ghost sm" href={api.sourceFileUrl(source)} target="_blank" rel="noreferrer">فتح الأصلي</a>
          <X size={18} style={{ cursor: "pointer", marginInlineStart: 10 }} onClick={onClose} /></div>
        {!data && <div className="empty">جاري التحميل…</div>}
        {data && kind === "image" && <div className="viewer-img"><img src={api.sourceFileUrl(source)} alt={source} /></div>}
        {data && kind === "pdf" && (
          <>
            {data.pages?.length > 0
              ? <div className="pdf-pages">{data.pages.map((p) => <img key={p} src={api.pageUrl(p)} alt={p} loading="lazy" />)}</div>
              : <object data={api.sourceFileUrl(source)} type="application/pdf" width="100%" height="600px"><div className="empty">تعذّر العرض</div></object>}
            <div style={{ padding: "0 16px 16px" }}>
              <div className="label">النص المستخرج (يشمل الجداول ووصف الصور)</div>
              {chunks.map((c) => <div key={c.id} className="viewer-chunk">
                <span className="pill" style={{ marginBottom: 6 }}>{TYPE_AR[c.type] || c.type}{c.page ? ` · ص${c.page}` : ""}</span>
                <div style={{ fontSize: 13.5, lineHeight: 1.8, whiteSpace: "pre-wrap" }}>{c.text}</div></div>)}
            </div>
          </>
        )}
        {data && (kind === "text" || kind === "docx") && (
          <div style={{ padding: 16 }}>
            <div className="search-bar" style={{ marginBottom: 12 }}><Search size={16} color="var(--muted)" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="ابحث داخل المستند…" /></div>
            {chunks.map((c) => <div key={c.id} className="viewer-chunk">
              <span className="pill" style={{ marginBottom: 6 }}>{TYPE_AR[c.type] || c.type}{c.page ? ` · ص${c.page}` : ""}</span>
              <div style={{ fontSize: 14, lineHeight: 1.9, whiteSpace: "pre-wrap" }}>{highlight(c.text, q)}</div></div>)}
            {chunks.length === 0 && <div className="empty">لا نتائج</div>}
          </div>
        )}
      </div>
    </div>
  );
}

function highlight(text, q) {
  if (!q) return text;
  const parts = (text || "").split(q);
  return parts.map((p, i) => i < parts.length - 1
    ? <React.Fragment key={i}>{p}<span className="hl">{q}</span></React.Fragment>
    : <React.Fragment key={i}>{p}</React.Fragment>);
}
