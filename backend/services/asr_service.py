"""ASR micro-service — QwenCleo-ASR (Egyptian + code-switching).

Runs in the `test-qwen` conda env. Loads the model on the pinned GPU and exposes:

  POST /transcribe        {audio_b64 | path}  -> {text}
  WS   /ws/stream         binary float32 frames @16k -> {"text","is_final"} chunks
  GET  /health

Streaming uses qwencleo_asr.ChunkedSession (rolling-window transcription) so the
orchestrator gets near-real-time partials without standing up a second vLLM server.
"""
from __future__ import annotations

import base64
import io
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CFG  # noqa: E402

# Pin GPU before importing torch-heavy libs.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", str(CFG.system.gpu_device))

import soundfile as sf  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, WebSocket, WebSocketDisconnect  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from logging_setup import setup as _setup_logging, preview  # noqa: E402

log = _setup_logging("asr", "ASR", CFG.logging.level)

_CFG = CFG.asr
app = FastAPI(title="Voice Agent ASR")
_asr = None  # lazy global


def get_asr():
    global _asr
    if _asr is None:
        from qwencleo_asr import QwenCleoASR
        log.info("loading %s on %s (%s)…", _CFG.model_id, _CFG.device, _CFG.dtype)
        _asr = QwenCleoASR(_CFG.model_id, device=_CFG.device, dtype=_CFG.dtype,
                           default_language=_CFG.language)
        # warm up
        _asr.transcribe(_silence_wav(), language=_CFG.language)
        log.info("ASR ready.")
    return _asr


def _silence_wav() -> str:
    p = "/tmp/va_asr_warm.wav"
    sf.write(p, np.zeros(_CFG.sample_rate, np.float32), _CFG.sample_rate)
    return p


class TranscribeReq(BaseModel):
    audio_b64: str | None = None
    path: str | None = None
    language: str | None = None


@app.get("/health")
def health():
    return {"ok": True, "model": _CFG.model_id, "ready": _asr is not None}


@app.post("/transcribe")
def transcribe(req: TranscribeReq):
    asr = get_asr()
    t0 = time.time()
    if req.path:
        path = req.path
        dur = 0.0
    else:
        raw = base64.b64decode(req.audio_b64 or "")
        path = "/tmp/va_asr_in.wav"
        # accept either a wav container or raw float32 @ sample_rate
        try:
            data, sr = sf.read(io.BytesIO(raw), dtype="float32")
        except Exception:
            data = np.frombuffer(raw, dtype=np.float32)
            sr = _CFG.sample_rate
        sf.write(path, data, sr)
        dur = len(data) / float(sr or 1)
        log.info("ASR    request  bytes=%d audio=%.2fs sr=%d", len(raw), dur, sr)
    r = asr.transcribe(path, language=req.language or _CFG.language)
    dt = time.time() - t0
    log.info("ASR    done     took=%.2fs rtf=%.2f text=%r",
             dt, (dt / dur if dur else 0), preview(r.text))
    return {"text": r.text}


def _usable(text: str, previous: str) -> bool:
    """Reject transcripts that are almost certainly hallucinated.

    On quiet/noisy audio QwenCleo tends to emit stock phrases or a single token
    repeated. Combined with the energy gate this keeps junk out of the UI.
    """
    t = (text or "").strip()
    if len(t) < 2:
        return False
    if t == (previous or "").strip():
        return False
    words = t.split()
    if len(words) >= 4 and len(set(words)) <= max(1, len(words) // 3):
        return False                      # "انت انت انت انت"
    return True


@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    """Receive float32 PCM frames (mono @ sample_rate) as binary messages; emit
    transcription chunks as JSON. Send the text `"flush"` to force a final emit."""
    from qwencleo_asr.streaming import ChunkedSession
    await ws.accept()
    asr = get_asr()
    sess = ChunkedSession(asr, sr=_CFG.sample_rate, chunk_s=_CFG.chunk_seconds,
                          language=_CFG.language)
    log.info("WS     open     asr stream (chunk=%.1fs sr=%d)", _CFG.chunk_seconds, _CFG.sample_rate)
    t0 = time.time(); samples = 0; partials = 0; first = None; dropped = 0
    silence_floor = float(getattr(_CFG, "silence_rms", 0.008))
    last_text = ""
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if "bytes" in msg and msg["bytes"] is not None:
                frame = np.frombuffer(msg["bytes"], dtype=np.float32)
                # Never feed silence to the recognizer: on near-silent audio it
                # invents text (e.g. "انا بحبك انت بتحبني"). The client gates with
                # VAD too; this is the server-side safety net.
                rms = float(np.sqrt(np.mean(frame ** 2))) if frame.size else 0.0
                if rms < silence_floor:
                    dropped += 1
                    continue
                samples += len(frame)
                for chunk in sess.add(frame):
                    txt = (chunk.text or "").strip()
                    if not _usable(txt, last_text):
                        log.info("ASR    dropped  implausible/repeat text=%r", preview(txt, 50))
                        continue
                    last_text = txt
                    partials += 1
                    if first is None:
                        first = time.time() - t0
                        log.info("ASR    first    partial after %.2fs", first)
                    log.info("ASR    partial  #%d final=%s text=%r",
                             partials, chunk.is_final, preview(txt, 60))
                    await ws.send_json({"text": txt, "is_final": chunk.is_final})
            elif msg.get("text") == "flush":
                for chunk in sess.flush():
                    txt = (chunk.text or "").strip()
                    if not _usable(txt, last_text):
                        log.info("ASR    dropped  final implausible/repeat text=%r", preview(txt, 50))
                        continue
                    last_text = txt
                    log.info("ASR    final    text=%r", preview(txt, 80))
                    await ws.send_json({"text": txt, "is_final": True})
            elif msg.get("text") == "close":
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.exception("WS error: %s", e)
    log.info("WS     closed   asr stream speech=%.1fs partials=%d silent_frames_dropped=%d",
             samples / float(_CFG.sample_rate), partials, dropped)


if __name__ == "__main__":
    get_asr()
    uvicorn.run(app, host=_CFG.host, port=_CFG.port, log_level="warning")
