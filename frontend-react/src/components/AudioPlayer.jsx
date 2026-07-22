import React, { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import { Play, Pause, Download, Volume2, Loader2 } from "lucide-react";

// Waveform audio player built on wavesurfer.js.
//
// MediaRecorder's webm blobs carry no duration in their header, so a plain
// <audio> reports `Infinity` (rendered as "Infinity:NaN") and its progress bar
// never moves. wavesurfer decodes the audio itself, so duration and seeking are
// always correct regardless of container metadata.
export default function AudioPlayer({ src, compact = false, label }) {
  const holder = useRef(null);
  const ws = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [ready, setReady] = useState(false);
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!holder.current || !src) return;
    setReady(false); setFailed(false); setCur(0); setDur(0);
    const css = getComputedStyle(document.documentElement);
    const accent = css.getPropertyValue("--acc").trim() || "#22c55e";
    const idle = css.getPropertyValue("--line-2").trim() || "#c9ced8";

    const inst = WaveSurfer.create({
      container: holder.current,
      height: compact ? 34 : 56,
      waveColor: idle,
      progressColor: accent,
      cursorColor: accent,
      cursorWidth: 2,
      barWidth: 2.5,
      barGap: 2,
      barRadius: 3,
      normalize: true,
      dragToSeek: true,
      url: src,
    });
    ws.current = inst;

    inst.on("ready", () => { setReady(true); setDur(inst.getDuration() || 0); });
    inst.on("decode", (d) => setDur(d || 0));
    inst.on("timeupdate", (t) => setCur(t || 0));
    inst.on("play", () => setPlaying(true));
    inst.on("pause", () => setPlaying(false));
    inst.on("finish", () => { setPlaying(false); setCur(0); });
    inst.on("error", () => { setFailed(true); setReady(false); });

    return () => { try { inst.destroy(); } catch {} ws.current = null; };
  }, [src, compact]);

  const toggle = () => { try { ws.current?.playPause(); } catch {} };
  const fmt = (s) => (Number.isFinite(s) && s >= 0)
    ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}` : "0:00";

  return (
    <div className={"aplayer" + (compact ? " compact" : "")}>
      <button className="ap-play" onClick={toggle} disabled={!ready}
        title={playing ? "إيقاف مؤقت" : "تشغيل"}>
        {!ready && !failed ? <Loader2 size={compact ? 15 : 18} className="spin" />
          : playing ? <Pause size={compact ? 15 : 18} /> : <Play size={compact ? 15 : 18} />}
      </button>
      <div className="ap-main">
        {label && <div className="ap-label"><Volume2 size={12} /> {label}</div>}
        <div ref={holder} className="ap-wave-host" />
        <div className="ap-time">
          <span>{fmt(cur)}</span>
          <span>{failed ? "تعذّر التحميل" : ready ? fmt(dur) : "…"}</span>
        </div>
      </div>
      {!compact && <a className="ap-dl" href={src} download title="تحميل"><Download size={16} /></a>}
    </div>
  );
}
