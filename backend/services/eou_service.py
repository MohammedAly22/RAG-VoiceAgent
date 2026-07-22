"""End-of-Utterance (EoU) / turn-detection micro-service.

Decides whether the user has *finished* their turn, so the agent knows when to
stop listening and start responding (and, combined with VAD, enables barge-in).

Two signals are combined:
  1. VAD / silence endpointing  — handled upstream by the ASR stream + the client
     (min_silence_ms in config). This service focuses on the *semantic* signal.
  2. Semantic EoU — is the transcribed Arabic text a complete turn, or does it
     trail off on a connector / filler (so we should keep waiting)?

The real-time LiveKit path additionally uses livekit's multilingual turn-detector
model (Arabic-capable) inside the agent; this HTTP service serves the browser
voice path and anything that wants a quick, dependency-light EoU decision.

  POST /eou   {"text": "...", "language": "ar"}  -> {"complete": bool, "prob": float}
  GET  /health
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CFG  # noqa: E402

from logging_setup import setup as _setup_logging, preview  # noqa: E402

log = _setup_logging("eou", "EOU", CFG.logging.level)

_CFG = CFG.eou
app = FastAPI(title="Voice Agent EoU")

# Arabic connectors / fillers that usually mean "the speaker will continue".
_TRAILING = {
    "و", "أو", "او", "لكن", "بس", "علشان", "عشان", "لأن", "لان", "يعني", "زي",
    "عن", "في", "من", "على", "مع", "إن", "ان", "أنا", "انا", "هو", "هي", "اللي",
    "الي", "امم", "اممم", "اه", "ايه", "طب", "يبقى",
}
_QUESTION = ("؟", "?")
_TERMINAL = (".", "!", "؟", "?", "،")


class EoUReq(BaseModel):
    text: str
    language: str | None = "ar"


def eou_probability(text: str) -> float:
    """Return P(turn complete) in [0,1] from a fast Arabic heuristic."""
    t = (text or "").strip()
    if not t:
        return 0.0
    words = re.findall(r"[\w؀-ۿ]+", t)
    if not words:
        return 0.0
    last = words[-1]
    prob = 0.6  # neutral prior for a non-empty utterance

    if t.endswith(_QUESTION):
        prob = 0.95
    elif t.endswith(_TERMINAL):
        prob = 0.9
    if last in _TRAILING:            # trails off on a connector → keep waiting
        prob = min(prob, 0.25)
    if len(words) <= 1:              # a single word is rarely a full turn
        prob = min(prob, 0.35)
    if len(words) >= 6 and prob < 0.6:
        prob = 0.65                  # a long-enough phrase is probably complete
    return round(prob, 3)


@app.get("/health")
def health():
    return {"ok": True, "model": _CFG.model, "threshold": _CFG.threshold}


@app.post("/eou")
def eou(req: EoUReq):
    p = eou_probability(req.text)
    complete = p >= _CFG.threshold
    log.info("EOU    decide   prob=%.2f thr=%.2f complete=%s text=%r",
             p, _CFG.threshold, complete, preview(req.text, 60))
    return {"complete": complete, "prob": p, "threshold": _CFG.threshold}


if __name__ == "__main__":
    uvicorn.run(app, host=_CFG.host, port=_CFG.port, log_level="warning")
