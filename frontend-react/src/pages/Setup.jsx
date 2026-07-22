import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Bot, Wand2, Upload, Check, ArrowLeft, Loader2, Trash2 } from "lucide-react";
import { api } from "../lib/api.js";

// 3-step Setup wizard: identity → persona (category / Other + LLM suggest) → data.
export default function Setup({ cfg, onDone }) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState(cfg.agent?.name || "");
  const [category, setCategory] = useState(cfg.agent?.category || "restaurant");
  const [prompt, setPrompt] = useState(cfg.agent?.system_prompt || "");
  const [greeting, setGreeting] = useState(cfg.agent?.greeting || "");
  const [otherDesc, setOtherDesc] = useState("");
  const [suggesting, setSuggesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [sources, setSources] = useState([]);
  const [uploading, setUploading] = useState(false);

  const cats = cfg.categories || [];
  const pickCategory = (c) => {
    setCategory(c.id);
    if (c.id !== "other") setPrompt((c.prompt || "").trim());
    else setPrompt("");
  };

  const suggest = async () => {
    if (!otherDesc.trim()) return;
    setSuggesting(true);
    try {
      const r = await api.suggestPrompt({ description: otherDesc, name });
      setPrompt(r.prompt);
    } catch (e) { alert("تعذّر توليد الـ prompt: " + e.message); }
    setSuggesting(false);
  };

  const loadData = () => api.data().then((r) => setSources(r.sources || []));
  const onUpload = async (files) => {
    setUploading(true);
    for (const f of files) { try { await api.upload(f); } catch (e) { alert("فشل رفع " + f.name + ": " + e.message); } }
    await loadData();
    setUploading(false);
  };

  const finish = async () => {
    setSaving(true);
    try {
      await api.saveConfig({
        agent: { name, category, system_prompt: prompt, greeting, configured: true },
      });
      onDone();
    } catch (e) { alert("فشل الحفظ: " + e.message); setSaving(false); }
  };

  return (
    <div className="content" style={{ height: "100vh", overflow: "auto" }}>
      <div className="wizard">
        <div className="brand" style={{ padding: "6px 0 22px" }}>
          <div className="logo"><Bot size={20} /></div>
          <div><h1>إعداد الوكيل الصوتي</h1><small>{cfg.brand} · Voice Agent</small></div>
        </div>
        <div className="steps">
          {[0, 1, 2].map((i) => <div key={i} className={"step-dot" + (i <= step ? " on" : "")} />)}
        </div>

        <AnimatePresence mode="wait">
        <motion.div key={step} initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -16 }} transition={{ duration: 0.22 }}>
        {step === 0 && (
          <div className="card" style={{ padding: 26 }}>
            <h3 style={{ marginTop: 0 }}>١. هوية الوكيل</h3>
            <label className="label">اسم الوكيل</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="مثال: مساعد مطعم بيت الطعمية" />
            <div style={{ height: 16 }} />
            <label className="label">جملة الترحيب (تُقال في بداية المكالمة الصوتية)</label>
            <input className="input" value={greeting} onChange={(e) => setGreeting(e.target.value)} placeholder="أهلاً بيك! أنا مساعد المطعم…" />
            <div style={{ marginTop: 22, display: "flex", justifyContent: "flex-end" }}>
              <button className="btn" disabled={!name.trim()} onClick={() => setStep(1)}>التالي</button>
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="card" style={{ padding: 26 }}>
            <h3 style={{ marginTop: 0 }}>٢. غرض الوكيل (الشخصية)</h3>
            <p className="hint" style={{ marginTop: 0 }}>اختر فئة جاهزة بنظام prompt تفصيلي، أو «غير ذلك» واكتب الغرض ودَع الذكاء الاصطناعي يقترح لك prompt.</p>
            <div className="cat-grid">
              {cats.map((c) => (
                <button key={c.id} className={"cat" + (category === c.id ? " sel" : "")} onClick={() => pickCategory(c)}>
                  <div className="t">{c.label}</div>
                  <div className="d">{c.id === "other" ? "غرض مخصص + اقتراح آلي" : (c.prompt || "").slice(0, 70) + "…"}</div>
                </button>
              ))}
            </div>

            {category === "other" && (
              <div style={{ marginTop: 18 }}>
                <label className="label">اوصف غرض الوكيل باختصار</label>
                <div style={{ display: "flex", gap: 8 }}>
                  <input className="input" value={otherDesc} onChange={(e) => setOtherDesc(e.target.value)} placeholder="مثال: مساعد لمكتبة يجاوب عن الكتب والمواعيد والأسعار" />
                  <button className="btn" style={{ whiteSpace: "nowrap" }} disabled={suggesting || !otherDesc.trim()} onClick={suggest}>
                    {suggesting ? <Loader2 className="spin" size={16} /> : <Wand2 size={16} />} اقترح prompt
                  </button>
                </div>
              </div>
            )}

            <div style={{ marginTop: 18 }}>
              <label className="label">الـ System Prompt (قابل للتعديل)</label>
              <textarea className="textarea" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="سيظهر هنا الـ system prompt التفصيلي…" />
            </div>

            <div style={{ marginTop: 22, display: "flex", justifyContent: "space-between" }}>
              <button className="btn ghost" onClick={() => setStep(0)}><ArrowLeft size={16} /> رجوع</button>
              <button className="btn" disabled={!prompt.trim()} onClick={() => { setStep(2); loadData(); }}>التالي</button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="card" style={{ padding: 26 }}>
            <h3 style={{ marginTop: 0 }}>٣. قاعدة المعرفة (البيانات)</h3>
            <p className="hint" style={{ marginTop: 0 }}>ارفع مستندات (PDF / DOCX / TXT / MD) — هتتقسّم وتتحوّل إلى متجهات (embeddings) وتتخزن في قاعدة FAISS. يدعم الجداول والصور (multimodal).</p>
            <Dropzone onFiles={onUpload} busy={uploading} />
            <div style={{ marginTop: 16 }}>
              {sources.length === 0 && <div className="hint">لا توجد بيانات بعد. يمكنك المتابعة والإضافة لاحقاً من تبويب «البيانات».</div>}
              {sources.map((s) => (
                <div key={s.source} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 4px", borderBottom: "1px solid var(--line)" }}>
                  <Check size={16} color="var(--ok)" />
                  <b style={{ fontSize: 14 }}>{s.source}</b>
                  <span className="hint" style={{ margin: 0 }}>{s.chunks} مقطع · {s.pages} صفحة</span>
                  <div className="spacer" style={{ flex: 1 }} />
                  <button className="iconbtn" onClick={async () => { await api.removeSource(s.source); loadData(); }}><Trash2 size={15} /></button>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 24, display: "flex", justifyContent: "space-between" }}>
              <button className="btn ghost" onClick={() => setStep(1)}><ArrowLeft size={16} /> رجوع</button>
              <button className="btn" disabled={saving} onClick={finish}>
                {saving ? <Loader2 className="spin" size={16} /> : <Check size={16} />} ابدأ الجلسة
              </button>
            </div>
          </div>
        )}
        </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

function Dropzone({ onFiles, busy }) {
  const [drag, setDrag] = useState(false);
  const inp = React.useRef();
  return (
    <div className={"dropzone" + (drag ? " drag" : "")}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); onFiles([...e.dataTransfer.files]); }}
      onClick={() => inp.current?.click()}>
      {busy ? <Loader2 className="spin" size={22} /> : <Upload size={22} />}
      <div style={{ marginTop: 8 }}>{busy ? "جاري الرفع والفهرسة…" : "اسحب الملفات هنا أو اضغط للاختيار"}</div>
      <input ref={inp} type="file" multiple hidden accept=".pdf,.docx,.txt,.md"
        onChange={(e) => onFiles([...e.target.files])} />
    </div>
  );
}
