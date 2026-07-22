"""Lahgtna-OmniVoice TTS engine — a drop-in alternative to VoiceTutTTS.

Lahgtna (`oddadmix/lahgtna-omnivoice-v2`) is another fine-tune of OmniVoice 0.6B
that follows Arabic diacritics (tashkeel) more faithfully. It runs in the SAME
`omnivoice` conda env as VoiceTut.

It does NOT ship its own speakers, so we **reuse VoiceTut's 17 built-in reference
speakers** (audio + reference text) AND VoiceTut's `ArabicNormalizer` text pipeline
(numbers, dates, abbreviations, diacritics, lexicon). That keeps voices and text
handling identical across both engines — only the acoustic model differs.

The public API mirrors `VoiceTutTTS` so `tts_service.py` can use either engine
interchangeably: `list_speakers()`, `registry`, `synthesize(text, speaker, …)`,
and `stream(text, speaker, …)`.
"""
from __future__ import annotations

import logging
from typing import Iterator, Optional, Tuple

import numpy as np

log = logging.getLogger("tts.lahgtna")

# The Lahgtna model is trained with its OWN dialect ids (from the Lahgtna-OmniVoice
# fork). The OmniVoice build installed here is the base fork and doesn't know them,
# so `_resolve_language("eg")` would fall back to language-agnostic mode and lose the
# Egyptian-Lahgtna conditioning. The id is just inserted as a plain text style token
# (<|lang_start|>eg<|lang_end|>), so we only need it to be *accepted* — we register
# the Lahgtna dialect map into the in-memory LANG tables (no site-package edit).
# Source: https://github.com/Oddadmix/Lahgtna-OmniVoice  (lang_map.py)
_LAHGTNA_DIALECTS = {
    "egyptian lahgtna": "eg", "saudi lahgtna": "sa", "moroccan lahgtna": "ma",
    "bahraini lahgtna": "bh", "sudanese lahgtna": "sd", "iraqi lahgtna": "iq",
    "lebanese lahgtna": "lb", "syrian lahgtna": "sy", "libyan lahgtna": "ly",
    "palestinian lahgtna": "ps", "tunisian lahgtna": "tn", "algerian lahgtna": "dz",
    "yemeni lahgtna": "ye",
}


def _register_lahgtna_dialects() -> None:
    """Make the Lahgtna dialect ids (eg, sa, …) valid in the installed OmniVoice."""
    try:
        from omnivoice.utils import lang_map
        lang_map.LANG_NAME_TO_ID.update(_LAHGTNA_DIALECTS)
        lang_map.LANG_NAMES |= set(_LAHGTNA_DIALECTS.keys())
        lang_map.LANG_IDS |= set(_LAHGTNA_DIALECTS.values())
    except Exception as e:  # noqa: BLE001
        log.warning("could not register Lahgtna dialect ids: %s", e)


class LahgtnaTTS:
    def __init__(self, model, registry, normalizer, *, language: str = "eg",
                 sample_rate: int = 24000):
        self.model = model
        self.registry = registry          # reused VoiceTut SpeakerRegistry
        self.normalizer = normalizer      # reused VoiceTut ArabicNormalizer
        self.language = language
        self.sample_rate = sample_rate

    # ------------------------------------------------------------------ loading
    @classmethod
    def from_pretrained(cls, model_id: str, *, device: str = "cuda:0",
                        dtype: str = "float16", language: str = "eg",
                        voicetut_repo: str = "mohammedaly22/VoiceTut-TTS",
                        sample_rate: int = 24000) -> "LahgtnaTTS":
        import torch
        from omnivoice import OmniVoice
        from voicetut_tts import ArabicNormalizer
        from voicetut_tts.engine import VoiceTutTTS

        _register_lahgtna_dialects()      # make "eg" (Egyptian Lahgtna) a valid id
        torch_dtype = getattr(torch, dtype, torch.float16)
        dev = device if ":" in device else f"{device}:0"
        log.info("loading Lahgtna %s on %s (%s)…", model_id, dev, dtype)
        model = OmniVoice.from_pretrained(model_id, device_map=dev, dtype=torch_dtype)

        # Borrow VoiceTut's built-in speaker registry (the 17 reference voices live
        # inside the VoiceTut HF repo) + its text normalizer.
        ref_path = VoiceTutTTS._find_references(voicetut_repo)
        if not ref_path:
            raise RuntimeError("Could not locate VoiceTut reference_speakers/references.json")
        from voicetut_tts import SpeakerRegistry
        registry = SpeakerRegistry(ref_path)
        normalizer = ArabicNormalizer()
        log.info("Lahgtna ready — reusing %d VoiceTut speakers.", len(registry))
        return cls(model, registry, normalizer, language=language, sample_rate=sample_rate)

    # ------------------------------------------------------------------ helpers
    def list_speakers(self):
        return self.registry.all()

    def _ref(self, speaker: Optional[str]) -> Tuple[str, str]:
        spk = self.registry.get(speaker)
        return spk.audio_path, spk.reference_text

    def _gen(self, text: str, speaker: Optional[str], normalize: bool) -> np.ndarray:
        if normalize:
            text = self.normalizer.normalize(text)
        ref_audio, ref_text = self._ref(speaker)
        audios = self.model.generate(
            text=text, language=self.language,
            ref_audio=ref_audio, ref_text=ref_text,
        )
        wav = audios[0] if isinstance(audios, (list, tuple)) else audios
        if hasattr(wav, "detach"):
            wav = wav.detach().cpu().numpy()
        return np.asarray(wav, dtype=np.float32).reshape(-1)

    # ------------------------------------------------------------------ public API
    def synthesize(self, text: str, *, speaker: Optional[str] = None,
                   normalize: bool = True, **_ignored) -> np.ndarray:
        """One-shot synth. Extra VoiceTut kwargs (num_step…) are ignored by Lahgtna."""
        return self._gen(text, speaker, normalize)

    def stream(self, text: str, *, speaker: Optional[str] = None,
               normalize: bool = True, **_ignored) -> Iterator[Tuple[int, np.ndarray]]:
        """Yield (sample_rate, chunk) per sentence — same shape as VoiceTut.stream."""
        from voicetut_tts import split_sentences
        sents = split_sentences(text) or [text]
        for sent in sents:
            if not sent.strip():
                continue
            yield self.sample_rate, self._gen(sent, speaker, normalize)
