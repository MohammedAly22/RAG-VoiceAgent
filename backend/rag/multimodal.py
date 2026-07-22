"""Multimodal helpers for ingestion.

Images and tables carry information that plain text extraction misses. At ingest
time we caption them with Gemini vision (Arabic) and embed the *caption* text so
they become retrievable; the UI then shows the source page screenshot.

Falls back gracefully (returns an empty caption) if Gemini is unavailable, so
ingestion never hard-fails on the multimodal path.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CFG  # noqa: E402

log = logging.getLogger("rag.multimodal")

_CAPTION_PROMPT = (
    "صِف محتوى هذه الصورة بالعربية بشكل دقيق ومفصّل بحيث يمكن البحث عنها لاحقاً. "
    "لو فيها جدول، استخرج صفوفه وأعمدته كنص. لو فيها قائمة أسعار أو منيو، اذكر "
    "الأصناف وأسعارها. اكتب الوصف فقط بدون مقدمات."
)


def _gemini_client():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=key)
    except Exception as e:  # noqa: BLE001
        log.warning("gemini client unavailable: %s", e)
        return None


_PAGE_PROMPT = (
    "اقرأ محتوى صفحة المستند دي بالكامل وحوّلها لنص عربي منظّم ودقيق. "
    "استخرج كل الجداول كصفوف نصية بالشكل: الصنف — السعر. "
    "حافظ على الأرقام والأسعار زي ما هي بالظبط، واكتب العناوين والأقسام. "
    "اكتب النص المستخرج فقط بدون أي مقدمات أو تعليق."
)


def read_page_image(image_path: str) -> str:
    """Read a rendered PDF page with vision → accurate Arabic text.

    Used when a PDF's embedded text layer is shaped/bidi-mangled (Arabic
    presentation forms with reversed digit runs), which would otherwise put
    wrong prices/numbers into the knowledge base.
    """
    if not CFG.rag.multimodal:
        return ""
    client = _gemini_client()
    if client is None:
        return ""
    try:
        from google.genai import types
        data = Path(image_path).read_bytes()
        resp = client.models.generate_content(
            model=CFG.llm.gemini.model,
            contents=[types.Part.from_bytes(data=data, mime_type="image/png"), _PAGE_PROMPT],
        )
        return (resp.text or "").strip()
    except Exception as e:  # noqa: BLE001
        log.warning("page vision read failed for %s: %s", image_path, e)
        return ""


def caption_image(image_path: str) -> str:
    """Return an Arabic caption/extraction for an image file, or "" on failure."""
    if not CFG.rag.multimodal:
        return ""
    client = _gemini_client()
    if client is None:
        return ""
    try:
        from google.genai import types
        data = Path(image_path).read_bytes()
        mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
        resp = client.models.generate_content(
            model=CFG.llm.gemini.model,
            contents=[
                types.Part.from_bytes(data=data, mime_type=mime),
                _CAPTION_PROMPT,
            ],
        )
        return (resp.text or "").strip()
    except Exception as e:  # noqa: BLE001
        log.warning("caption failed for %s: %s", image_path, e)
        return ""
