"""TTS micro-service — VoiceTut-TTS (OmniVoice 0.6B, 17 voices + cloning).

Runs in the `omnivoice` conda env. Loads the model on the pinned GPU and exposes:

  GET  /health
  GET  /speakers                 -> [{speaker_id, speaker_name, gender, tags, ...}]
  GET  /speakers/{name}/audio    -> reference wav (for the Settings voice cards)
  POST /synthesize  {text, voice}-> wav bytes (one shot)
  WS   /ws/stream                -> stream sentence chunks as int16 PCM @ sample_rate

Streaming yields one audio chunk per sentence (VoiceTut .stream), so the caller
starts playback after the first short sentence — minimal time-to-first-audio.
"""
from __future__ import annotations

import io
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CFG  # noqa: E402

os.environ.setdefault("CUDA_VISIBLE_DEVICES", str(CFG.system.gpu_device))

import soundfile as sf  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException  # noqa: E402
from fastapi.responses import Response, FileResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from logging_setup import setup as _setup_logging, preview  # noqa: E402

log = _setup_logging("tts", "TTS", CFG.logging.level)

_CFG = CFG.tts
app = FastAPI(title="Voice Agent TTS")
_tts = None


# --- text hygiene -----------------------------------------------------------
# The agent cites its sources in text ("(المصدر: menu.md)") and may use markdown.
# None of that should ever be spoken, so strip it before synthesis.
_CITE = re.compile(r"\((?:المصدر|المصادر|Source)\s*:[^)]*\)")
_BRACKET_CITE = re.compile(r"\[\d+\]")
_MD = re.compile(r"[*_`#>]+")
# Arabic-Indic / Extended digits → ASCII so the synthesizer voices them correctly.
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def clean_for_speech(text: str) -> str:
    t = _CITE.sub("", text or "")
    t = _BRACKET_CITE.sub("", t)
    t = re.sub(r"\((?:من|راجع)\s+[^)]*\.(?:md|pdf|docx|txt)\)", "", t)
    t = re.sub(r"[^\s]+\.(?:md|pdf|docx|txt)", "", t)   # bare filenames
    t = _MD.sub("", t)
    t = t.translate(_AR_DIGITS)
    t = re.sub(r"\s*\n\s*", " ، ", t)                    # newlines → short pause
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip(" ،-–—:")


_ENGINE = getattr(_CFG, "engine", "voicetut")


def get_tts():
    global _tts
    if _tts is None:
        if _ENGINE == "lahgtna":
            from lahgtna_tts import LahgtnaTTS
            mid = getattr(_CFG, "lahgtna_model_id", "oddadmix/lahgtna-omnivoice-v2")
            log.info("loading Lahgtna engine %s …", mid)
            _tts = LahgtnaTTS.from_pretrained(
                mid, device=_CFG.device,
                dtype=getattr(_CFG, "lahgtna_dtype", "float16"),
                language=getattr(_CFG, "lahgtna_language", "eg"),
                voicetut_repo=_CFG.model_id,
                sample_rate=_CFG.sample_rate)
        else:
            from voicetut_tts import VoiceTutTTS
            log.info("loading VoiceTut %s on %s (%s)…", _CFG.model_id, _CFG.device, _CFG.dtype)
            _tts = VoiceTutTTS.from_pretrained(_CFG.model_id, device=_CFG.device, dtype=_CFG.dtype)
        log.info("TTS ready (engine=%s) — %d speakers.", _ENGINE, len(_tts.list_speakers()))
    return _tts


def _gen_kwargs(num_step: int | None = None) -> dict:
    # Lahgtna ignores diffusion params; VoiceTut uses them. (Lahgtna also accepts
    # them harmlessly via **_ignored, but skip to be tidy.)
    if _ENGINE == "lahgtna":
        return {}
    return dict(num_step=int(num_step or _CFG.num_step),
                guidance_scale=_CFG.guidance_scale, speed=_CFG.speed)


class SynthReq(BaseModel):
    text: str
    voice: str | None = None
    num_step: int | None = None      # diffusion steps — lower = faster, slightly rougher


@app.get("/health")
def health():
    model = getattr(_CFG, "lahgtna_model_id", "") if _ENGINE == "lahgtna" else _CFG.model_id
    return {"ok": True, "engine": _ENGINE, "model": model, "ready": _tts is not None}


@app.get("/speakers")
def speakers():
    out = []
    for s in get_tts().list_speakers():
        d = s.to_public()
        d["audio_url"] = f"/speakers/{s.speaker_name}/audio"
        out.append(d)
    return {"speakers": out, "default": _CFG.active_voice}


@app.get("/speakers/{name}/audio")
def speaker_audio(name: str):
    try:
        spk = get_tts().registry.get(name)
    except Exception:
        raise HTTPException(404, "unknown speaker")
    return FileResponse(spk.audio_path)


@app.post("/synthesize")
def synthesize(req: SynthReq):
    tts = get_tts()
    voice = req.voice or _CFG.active_voice
    text = clean_for_speech(req.text)
    log.info("SYNTH  request  voice=%s steps=%s chars=%d text=%r",
             voice, req.num_step or _CFG.num_step, len(text), preview(text))
    if text != (req.text or "").strip():
        log.info("SYNTH  cleaned  removed citations/markdown (%d → %d chars)",
                 len((req.text or "").strip()), len(text))
    t0 = time.time()
    wav = tts.synthesize(text, normalize=True, speaker=voice, **_gen_kwargs(req.num_step))
    dt = time.time() - t0
    dur = len(wav) / float(_CFG.sample_rate)
    buf = io.BytesIO()
    sf.write(buf, wav, _CFG.sample_rate, format="WAV")
    log.info("SYNTH  done     voice=%s gen=%.2fs audio=%.2fs rtf=%.2f bytes=%d",
             voice, dt, dur, (dt / dur if dur else 0), buf.tell())
    return Response(content=buf.getvalue(), media_type="audio/wav")


@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    """Client sends {"text","voice"}; server streams int16 PCM chunks (binary),
    then a final JSON {"event":"end","sample_rate":...}."""
    await ws.accept()
    tts = get_tts()
    log.info("WS     open     tts stream")
    try:
        while True:
            req = await ws.receive_json()
            raw = (req.get("text") or "").strip()
            voice = req.get("voice") or _CFG.active_voice
            text = clean_for_speech(raw)
            if not text:
                await ws.send_json({"event": "end", "sample_rate": _CFG.sample_rate})
                continue
            log.info("STREAM request  voice=%s chars=%d text=%r", voice, len(text), preview(text))
            t0 = time.time(); ttfa = None; n = 0; total = 0
            for sr, chunk in tts.stream(text, speaker=voice, **_gen_kwargs(req.get('num_step'))):
                pcm = (np.clip(chunk, -1, 1) * 32767).astype(np.int16).tobytes()
                n += 1; total += len(chunk)
                if ttfa is None:
                    ttfa = time.time() - t0
                    log.info("STREAM TTFA     %.2fs (first audio chunk, %d samples)", ttfa, len(chunk))
                await ws.send_bytes(pcm)
                await ws.send_json({"event": "chunk", "index": n,
                                    "samples": int(len(chunk)), "sample_rate": int(sr)})
            dur = total / float(_CFG.sample_rate)
            log.info("STREAM done     chunks=%d audio=%.2fs gen=%.2fs ttfa=%.2fs",
                     n, dur, time.time() - t0, ttfa or 0)
            await ws.send_json({"event": "end", "sample_rate": _CFG.sample_rate,
                                "chunks": n, "duration_sec": round(dur, 2)})
    except WebSocketDisconnect:
        log.info("WS     closed   tts stream")
    except Exception as e:  # noqa: BLE001
        log.exception("WS error: %s", e)


if __name__ == "__main__":
    get_tts()
    uvicorn.run(app, host=_CFG.host, port=_CFG.port, log_level="warning")
