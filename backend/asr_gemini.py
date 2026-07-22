"""Gemini-based ASR — an alternative transcription provider.

Google's models transcribe Arabic with strong **code-switching** (Arabic ⇄
English) handling, which QwenCleo can miss. Selected via `asr.provider: gemini`.

Key correctness points learned the hard way:
  • The transcription instruction MUST go in `system_instruction`, NOT as a text
    part next to the audio — otherwise the model echoes the whole prompt back as
    if it were speech.
  • Silent / very-short / low-energy audio makes the model *invent* text (it
    returns a greeting or the prompt). So we gate on duration AND energy before
    ever calling the API, and scrub known hallucination patterns from the output.

Streaming re-transcribes a rolling buffer to produce progressive partials, then a
final on flush. Runs inside the app's `voiceagent` env (google-genai present).
"""
from __future__ import annotations

import io
import logging
import os
import re
import time

import numpy as np

log = logging.getLogger("app")

# Instruction lives in system_instruction so it never appears in the output.
_SYSTEM = (
    "أنت نظام تفريغ صوتي (speech-to-text) دقيق. مهمتك الوحيدة إنك تكتب الكلام المنطوق "
    "في المقطع الصوتي زي ما اتقال بالظبط، بالعربي، مع الحفاظ على أي كلمات إنجليزي زي ما "
    "هي (code-switching). "
    "قواعد صارمة: اكتب النص المنطوق فقط. ممنوع أي شرح أو تعليق أو ترجمة أو علامات. "
    "ممنوع تكتب أي تعليمات أو تعيد صياغة السؤال. "
    "لو المقطع صمت أو ضوضاء أو مفيش كلام واضح، رجّع نص فاضي تماماً (سلسلة فاضية)."
)
_USER = "فرّغ الكلام في المقطع ده:"

# Minimum voiced content before we bother the API.
_MIN_SECS = 0.45
_MIN_RMS = 0.012

_HALLUCINATIONS = (
    "أنت نظام تفريغ", "انت نظام تفريغ", "نظام تفريغ صوتي", "code-switching",
    "لو مفيش كلام", "رجّع نص فاضي", "اكتب النص المنطوق",
)


def _client():
    from google import genai
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set (needed for asr.provider=gemini)")
    return genai.Client(api_key=key)


def _wav_bytes(pcm_f32: np.ndarray, sr: int) -> bytes:
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, np.clip(pcm_f32, -1, 1), sr, format="WAV")
    return buf.getvalue()


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0


def _too_quiet(pcm: np.ndarray, sr: int) -> bool:
    return (pcm.size / max(sr, 1)) < _MIN_SECS or _rms(pcm) < _MIN_RMS


def _config():
    from google.genai import types
    return types.GenerateContentConfig(
        system_instruction=_SYSTEM,
        temperature=0.0,
        max_output_tokens=256,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )


def _collapse_repeats(t: str) -> str:
    """Remove Gemini's occasional stutter: an immediately-repeated phrase
    ("... نبذة سريعة نبذة سريعة ...") or a whole doubled transcript ("X X")."""
    words = t.split()
    n = len(words)
    # whole-string doubling: first half == second half
    if n >= 4 and n % 2 == 0 and words[: n // 2] == words[n // 2:]:
        words = words[: n // 2]
    # collapse an immediately-repeated run of 2..6 words (A B A B → A B)
    out: list[str] = []
    i = 0
    while i < len(words):
        matched = False
        for k in range(6, 1, -1):
            if i + 2 * k <= len(words) and words[i:i + k] == words[i + k:i + 2 * k]:
                out.extend(words[i:i + k]); i += 2 * k; matched = True; break
        if not matched:
            out.append(words[i]); i += 1
    # collapse a single word repeated back-to-back ("انت انت انت")
    dedup: list[str] = []
    for w in out:
        if not dedup or dedup[-1] != w:
            dedup.append(w)
    return " ".join(dedup)


def _clean(t: str) -> str:
    t = (t or "").strip().strip('"«»').strip()
    # drop any line that is (or contains) part of the instruction
    if any(h in t for h in _HALLUCINATIONS):
        # keep only text AFTER the echoed prompt, if any real speech follows
        for h in _HALLUCINATIONS:
            i = t.rfind(h)
            if i >= 0:
                t = t[i + len(h):]
        t = t.lstrip(" .،:-–—\n").strip()
    if any(h in t for h in _HALLUCINATIONS):     # still contaminated → discard
        return ""
    low = t.lower()
    if low in ("", "no speech", "(no speech)", "لا يوجد كلام", "[صمت]", "صمت", "silence", "."):
        return ""
    # collapse a single token repeated many times ("انت انت انت")
    words = t.split()
    if len(words) >= 4 and len(set(words)) <= max(1, len(words) // 3):
        return ""
    t = _collapse_repeats(re.sub(r"\s{2,}", " ", t).strip())
    return t.strip()


def transcribe_bytes(wav_bytes: bytes, model: str) -> str:
    from google.genai import types
    client = _client()
    resp = client.models.generate_content(
        model=model, config=_config(),
        contents=[types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"), _USER])
    return _clean((resp.text or "").strip())


async def atranscribe(pcm_f32: np.ndarray, sr: int, model: str) -> str:
    if _too_quiet(pcm_f32, sr):
        return ""
    from google.genai import types
    client = _client()
    resp = await client.aio.models.generate_content(
        model=model, config=_config(),
        contents=[types.Part.from_bytes(data=_wav_bytes(pcm_f32, sr), mime_type="audio/wav"), _USER])
    return _clean((resp.text or "").strip())


class GeminiStreamSession:
    """Accumulates VAD-gated speech and re-transcribes the rolling buffer for
    progressive partials, then a final on flush."""

    def __init__(self, sr: int, model: str, min_interval: float = 1.2) -> None:
        self.sr = sr
        self.model = model
        self.min_interval = min_interval
        self._buf: list[np.ndarray] = []
        self._last = 0.0
        self._new = 0
        self._last_text = ""       # most recent partial (cumulative for this utterance)
        self._last_secs = 0.0      # buffer length when _last_text was produced

    def add(self, frame: np.ndarray) -> None:
        self._buf.append(frame)
        self._new += len(frame)

    def _audio(self) -> np.ndarray:
        return np.concatenate(self._buf) if self._buf else np.zeros(1, np.float32)

    def secs(self) -> float:
        return sum(len(b) for b in self._buf) / float(self.sr)

    async def maybe_partial(self) -> str | None:
        now = time.time()
        if self._new / self.sr < 0.8 or (now - self._last) < self.min_interval:
            return None
        aud = self._audio()
        if _too_quiet(aud, self.sr):
            return None
        self._last = now; self._new = 0
        t = time.time()
        txt = await atranscribe(aud, self.sr, self.model)
        if txt:
            self._last_text = txt; self._last_secs = self.secs()
        log.info("ASR-GEM partial  buf=%.1fs took=%.2fs text=%r", self.secs(), time.time() - t, txt[:60])
        return txt or None

    async def final(self) -> str:
        aud = self._audio()
        if _too_quiet(aud, self.sr):
            log.info("ASR-GEM final    skipped (too quiet, buf=%.1fs rms=%.3f)", self.secs(), _rms(aud))
            self.reset(); return ""
        # Latency win: if a recent partial already covers essentially the whole
        # buffer, reuse it instead of paying for another full transcription.
        if self._last_text and (self.secs() - self._last_secs) < 0.6:
            txt = self._last_text
            log.info("ASR-GEM final    reused last partial (buf=%.1fs) text=%r", self.secs(), txt[:80])
            self.reset(); return txt
        t = time.time()
        txt = await atranscribe(aud, self.sr, self.model)
        log.info("ASR-GEM final    buf=%.1fs took=%.2fs text=%r", self.secs(), time.time() - t, txt[:80])
        self.reset()
        return txt

    def reset(self) -> None:
        self._buf = []; self._new = 0
        self._last_text = ""; self._last_secs = 0.0
