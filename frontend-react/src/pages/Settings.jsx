import React, { useEffect, useRef, useState } from "react";
import { Save, Loader2, Cpu, Cloud, Mic2, Play, Pause, Check, Volume2, Database, AudioLines } from "lucide-react";
import { api } from "../lib/api.js";
import { useToast } from "../components/Toast.jsx";

const SAMPLE = "أهلاً بيك في مطعم أبو السيد، أقدر أساعدك إزاي النهاردة؟";

export default function SettingsTab({ cfg, reloadCfg }) {
  const [backend, setBackend] = useState(cfg.llm?.backend || "gemini");
  const [asrProvider, setAsrProvider] = useState(cfg.asr?.provider || "qwencleo");
  const [ttsEngine, setTtsEngine] = useState(cfg.tts?.engine || "voicetut");
  const [voice, setVoice] = useState(cfg.tts?.active_voice || "Ahmed");
  const [voices, setVoices] = useState([]);
  const [saving, setSaving] = useState(false);
  const [playing, setPlaying] = useState(null);   // speaker name currently previewing
  const [loadingV, setLoadingV] = useState(null);
  const audioRef = useRef(null);
  const toast = useToast();

  useEffect(() => { api.voices().then((r) => setVoices(r.speakers || [])).catch(() => {}); }, []);
  useEffect(() => () => { audioRef.current?.pause(); }, []);

  // Instant preview: play the speaker's reference clip (no synthesis wait).
  const preview = async (name) => {
    if (playing === name) { audioRef.current?.pause(); setPlaying(null); return; }
    audioRef.current?.pause();
    setLoadingV(name);
    try {
      const a = new Audio(api.voiceSampleUrl(name));
      audioRef.current = a;
      a.onended = () => setPlaying(null);
      a.onerror = () => { setPlaying(null); setLoadingV(null); toast("تعذّر تشغيل العيّنة", "bad"); };
      await a.play(); setPlaying(name);
    } catch { toast("خدمة الصوت غير متاحة — شغّل TTS", "bad"); }
    setLoadingV(null);
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.saveConfig({ llm: { backend }, asr: { provider: asrProvider },
                             tts: { engine: ttsEngine, active_voice: voice } });
      await reloadCfg();
      if (asrProvider === "qwencleo" && !cfg.services?.asr)
        toast("اتحفظ — عشان QwenCleo يشتغل شغّل الخدمة: scripts/start_asr.sh (هتحمّل الموديل على الـ VRAM)", "ok");
      else if (asrProvider === "gemini")
        toast("اتحفظ — التفريغ دلوقتي عبر Gemini من غير ما نحمّل QwenCleo على الـ VRAM", "ok");
      else
        toast("تم الحفظ — الوكيل هيستخدم الإعدادات الجديدة فوراً", "ok");
    } catch (e) { toast("فشل الحفظ: " + e.message, "bad"); }
    setSaving(false);
  };

  return (
    <div className="page" style={{ maxWidth: 900 }}>
      <div style={{ marginBottom: 18 }}>
        <h3 style={{ margin: 0, color: "var(--ink)" }}>الإعدادات</h3>
        <div className="hint" style={{ margin: 0 }}>بدّل مزوّد الـ LLM أو محرك الصوت بدون تعديل أي كود — كل حاجة من config.yaml.</div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head"><Cpu size={17} /> نموذج اللغة (LLM)</div>
        <div className="card-body">
          <div className="grid2">
            <Opt sel={backend === "gemini"} onClick={() => setBackend("gemini")} icon={<Cloud size={18} />}
              t="Gemini (سحابي)" d={cfg.llm?.gemini_model || "gemini-2.5-flash"} />
            <Opt sel={backend === "vllm"} onClick={() => setBackend("vllm")} icon={<Cpu size={18} />}
              t="محلي عبر vLLM" d={cfg.llm?.vllm_model || "Qwen2.5-3B-Instruct"} />
          </div>
          {backend === "vllm" && <div className="hint">لازم تشغّل خدمة vLLM أولاً: <code>scripts/start_llm.sh</code></div>}
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head"><AudioLines size={17} /> محرك التعرف على الكلام (ASR)</div>
        <div className="card-body">
          <div className="grid2">
            <Opt sel={asrProvider === "qwencleo"} onClick={() => setAsrProvider("qwencleo")} icon={<Cpu size={18} />}
              t="QwenCleo (محلي)" d="عربي مصري + code-switching · GPU" />
            <Opt sel={asrProvider === "gemini"} onClick={() => setAsrProvider("gemini")} icon={<Cloud size={18} />}
              t="Gemini (سحابي)" d={`${cfg.asr?.gemini_model || "gemini-2.5-flash"} · جودة أعلى + code-switching`} />
          </div>
          {asrProvider === "qwencleo" && <div className="hint">بيتحمّل على الـ VRAM لما تختاره — شغّل الخدمة: <code>scripts/start_asr.sh</code></div>}
          {asrProvider === "gemini" && <div className="hint">تفريغ صوتي عبر Gemini مباشرة من التطبيق — من غير خدمة منفصلة ومن غير ما ياخد VRAM.</div>}
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head"><Mic2 size={17} /> محرك تحويل النص لصوت (TTS)</div>
        <div className="card-body">
          <div className="grid2">
            <Opt sel={ttsEngine === "voicetut"} onClick={() => setTtsEngine("voicetut")} icon={<Mic2 size={18} />} t="VoiceTut" d="OmniVoice · 17 صوت" />
            <Opt sel={ttsEngine === "lahgtna"} onClick={() => setTtsEngine("lahgtna")} icon={<Mic2 size={18} />} t="Lahgtna" d="التزام أفضل بالتشكيل" />
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head"><Volume2 size={17} /> صوت الوكيل
          <div className="spacer" /><span className="pill grad">{voice}</span></div>
        <div className="card-body">
          {voices.length === 0 && <div className="hint" style={{ margin: 0 }}>خدمة الـ TTS مش شغّالة — شغّلها لعرض الأصوات: <code>scripts/start_all.sh voice</code></div>}
          <div className="voice-grid">
            {voices.map((v) => {
              const n = v.speaker_name;
              return (
                <div key={n} className={"voice-card" + (voice === n ? " on" : "")} onClick={() => setVoice(n)}>
                  <div className="av">{n?.[0] || "?"}</div>
                  <div className="info">
                    <div className="nm">{n}</div>
                    <div className="gd">{v.gender === "female" ? "أنثى" : v.gender === "male" ? "ذكر" : "—"}</div>
                  </div>
                  <button className="play" title="استمع لعيّنة" onClick={(e) => { e.stopPropagation(); preview(n); }}>
                    {loadingV === n ? <Loader2 size={14} className="spin" />
                      : playing === n ? <Pause size={14} /> : <Play size={14} />}
                  </button>
                  {voice === n && <Check size={14} className="tick" />}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 18 }}>
        <div className="card-head"><Database size={17} /> قاعدة المعرفة (RAG)</div>
        <div className="card-body hint" style={{ margin: 0 }}>
          Embeddings: {cfg.rag?.embedding_model} · المخزن: {cfg.rag?.vector_store} · top_k={cfg.rag?.top_k} ·
          عتبة التطابق={cfg.rag?.score_threshold} · multimodal={String(cfg.rag?.multimodal)}
        </div>
      </div>

      <button className="btn" disabled={saving} onClick={save}>
        {saving ? <Loader2 className="spin" size={16} /> : <Save size={16} />} حفظ الإعدادات
      </button>
    </div>
  );
}

const Opt = ({ sel, onClick, icon, t, d }) => (
  <button className={"cat" + (sel ? " sel" : "")} onClick={onClick} style={{ display: "flex", gap: 12, alignItems: "center" }}>
    <span style={{ color: sel ? "var(--acc-3)" : "var(--muted)" }}>{icon}</span>
    <span><span className="t" style={{ display: "block", marginBottom: 2 }}>{t}</span><span className="d">{d}</span></span>
  </button>
);
