"""The RAG agent — low-latency streaming retrieve → generate.

Instead of a two-round-trip ReAct loop (decide-to-call-tool, then answer), this
does the classic RAG flow in a single streaming LLM call:

  1. retrieve  — one fast vector search (emitted to the UI as a tool call)
  2. generate  — one streaming LLM call grounded on the retrieved context,
                 with citations; refuses when nothing relevant is found.

This halves latency and streams real tokens (see agent/llm.astream_tokens).
The LiveKit realtime agent (backend/realtime/agent.py) keeps the @function_tool
form for Section 1; this surface is optimized for chat/voice responsiveness.

    async stream_answer(query, history, channel)  → UI events
    answer_once(query, history)                    → sync dict (CLI/tests)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CFG  # noqa: E402
from agent import llm  # noqa: E402
from agent.personas import build_system_prompt  # noqa: E402
from agent.logbus import QueryLog  # noqa: E402
from rag.store import get_store  # noqa: E402

log = logging.getLogger("agent.graph")


def invalidate() -> None:  # kept for API compatibility (Settings save)
    pass


def warmup() -> None:
    """Preload the embedder (so the first query doesn't pay the ~10s model load)
    and warm the LLM connection (so the first token isn't delayed by TLS setup)."""
    try:
        get_store().search("مرحبا", top_k=1)
    except Exception as e:  # noqa: BLE001
        log.warning("embedder warmup skipped: %s", e)
    try:
        if CFG.llm.backend == "gemini":
            import os
            from google import genai
            from google.genai import types
            c = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
            c.models.generate_content(model=CFG.llm.gemini.model, contents="hi",
                config=types.GenerateContentConfig(max_output_tokens=1,
                    thinking_config=types.ThinkingConfig(thinking_budget=0)))
        log.info("agent warmup done (embedder + LLM)")
    except Exception as e:  # noqa: BLE001
        log.warning("llm warmup skipped: %s", e)


def _retrieve(query: str) -> list[dict]:
    hits = get_store().search(query, top_k=CFG.rag.top_k)
    if not hits or hits[0]["score"] < CFG.rag.score_threshold:
        return []
    return hits


# Chit-chat / social turns must NOT hit the knowledge base — they're answered
# straight from the persona (greetings, thanks, goodbyes, yes/no, small talk).
_SOCIAL = {
    "السلام عليكم", "سلام عليكم", "السلام", "اهلا", "أهلا", "اهلاً", "أهلاً", "هاي", "هلا",
    "صباح الخير", "مساء الخير", "ازيك", "إزيك", "ازيك؟", "عامل ايه", "عامل إيه",
    "شكرا", "شكراً", "متشكر", "تمام", "اوك", "أوك", "ok", "تسلم", "الله يخليك",
    "مع السلامة", "باي", "سلام", "الحمد لله", "ماشي", "حلو", "برافو", "ايوه", "أيوه",
    "لا", "لأ", "نعم", "طيب", "زي ما انت", "مين انت", "مين إنت", "انت مين", "إنت مين",
    "تعرف تعمل ايه", "تقدر تعمل ايه", "بتعمل ايه", "مرحبا", "مرحباً",
}
_SOCIAL_PREFIX = ("السلام علي", "صباح ال", "مساء ال", "شكر", "متشكر", "مع السلام")


def _is_social(query: str) -> bool:
    """True for greetings/thanks/small-talk → answer from persona, skip retrieval."""
    import re
    q = re.sub(r"[!؟?.,،ـ]+", "", (query or "").strip()).strip()
    if not q:
        return True
    if q in _SOCIAL or q.lower() in _SOCIAL:
        return True
    if any(q.startswith(p) for p in _SOCIAL_PREFIX) and len(q.split()) <= 4:
        return True
    # very short utterances with no content words are social, not KB questions
    return len(q.split()) <= 2 and not any(ch.isdigit() for ch in q) and q in _SOCIAL


# Questions about the conversation itself (the user's name, what they said before,
# what the assistant just told them) must be answered from the chat history — NOT
# by searching the knowledge base. e.g. "انا اسمي ايه" after "انا اسمي محمد".
_MEMORY_HINTS = (
    "اسمي", "إسمي", "انا مين", "أنا مين", "مين انا", "مين أنا",
    "فاكر", "افتكر", "إفتكر", "بتفتكر", "تفتكر", "قلتلك", "قلت لك", "قولتلك",
    "قلتلي", "قلت لي", "اللي قلته", "اللي قلتهولك", "قبل كده", "قبل شوية",
    "اسمي ايه", "اسمي إيه", "انت قلت", "إنت قلت", "قولت", "كلمتك قبل",
)


def _is_memory_question(query: str, history: list[dict]) -> bool:
    """True when the query refers to the ongoing conversation (needs memory, not KB)."""
    if not history:
        return False
    q = (query or "").strip()
    return any(h in q for h in _MEMORY_HINTS)


def _context_block(hits: list[dict]) -> str:
    blocks = []
    for i, h in enumerate(hits, 1):
        cite = h["source"] + (f" ص{h['page']}" if h.get("page") else "")
        blocks.append(f"[{i}] (المصدر: {cite})\n{h['text']}")
    return "\n\n---\n\n".join(blocks)


def _public_docs(hits: list[dict]) -> list[dict]:
    out, seen = [], set()
    for c in hits:
        key = (c.get("source"), c.get("page"), c.get("chunk_index"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"source": c.get("source"), "page": c.get("page"), "type": c.get("type"),
                    "score": c.get("score"), "page_image": c.get("page_image"),
                    "snippet": (c.get("text") or "")[:400]})
    return out


async def stream_answer(query: str, history: list[dict] | None = None, channel: str = "chat"):
    """Yield UI events: tool_call → retrieved → token* → done."""
    history = history or []
    qlog = QueryLog(query, channel=channel)

    # 1) route: social chit-chat and memory questions skip the knowledge base.
    social = _is_social(query)
    memory = (not social) and _is_memory_question(query, history)
    if social or memory:
        hits = []
        decision = "social_no_retrieval" if social else "memory_no_retrieval"
        events = [{"type": "route", "decision": decision, "query": query}]
        log.info("ROUTE  %-20s q=%r", decision, (query or "")[:60])
    else:
        yield {"type": "tool_call", "tool": "retrieve_kb", "input": {"query": query}}
        hits = _retrieve(query)
        log.info("RAG    search   q=%r hits=%d top=%s", (query or "")[:60], len(hits),
                 f"{hits[0]['source']}@{hits[0]['score']:.2f}" if hits else "none")
        events = [{"type": "tool_call", "tool": "retrieve_kb", "query": query, "n_results": len(hits)}]
        if hits:
            yield {"type": "retrieved", "docs": _public_docs(hits)}
        else:
            events.append({"type": "no_context"})

    # 2) build the prompt
    system = build_system_prompt()
    if social:
        user_msg = (f"دي رسالة اجتماعية (تحية/شكر/سؤال عن نفسك)، مش سؤال عن معلومات. "
                    f"ردّ عليها بجملة واحدة قصيرة ودودة بالعامية المصرية من شخصيتك، "
                    f"من غير ما تذكر مصادر أو قاعدة معرفة، واعرض المساعدة.\nالرسالة: {query}")
    elif memory:
        user_msg = (f"السؤال ده بيخص المحادثة نفسها (حاجة قالها المستخدم أو قلتها إنت قبل كده)، "
                    f"مش سؤال عن قاعدة المعرفة. جاوب من سياق المحادثة اللي فوق بالعامية المصرية "
                    f"في جملة قصيرة. لو فعلاً مفيش المعلومة في المحادثة، قول إنك متعرفهاش لسه.\n"
                    f"السؤال: {query}")
    elif hits:
        # On the voice channel the answer is spoken — never ask for a written
        # citation, it would be read out loud by the TTS.
        cite_rule = ("من غير ما تذكر اسم أي ملف أو مصدر، وردّك يكون جملة أو جملتين "
                     "قصيرة مناسبة للنطق" if channel in ("voice", "livekit")
                     else "واذكر المصدر باختصار في النهاية")
        user_msg = (f"معلومات من قاعدة المعرفة:\n\n{_context_block(hits)}\n\n"
                    f"بناءً على المعلومات دي فقط، جاوب على السؤال ده بإيجاز بالعامية المصرية "
                    f"{cite_rule}:\n{query}")
    else:
        # No KB hit. It may still be answerable from the conversation (something the
        # user told us) — let the model use the history before it refuses.
        user_msg = (f"مفيش معلومات في قاعدة المعرفة تخص السؤال ده. لو الإجابة موجودة في سياق "
                    f"المحادثة اللي فوق، جاوب منها بالعامية المصرية. غير كده، اعتذر بأدب "
                    f"ووضّح إنك تقدر تساعد فقط في الأسئلة المتعلقة بمجالك، من غير ما تخمّن.\n"
                    f"السؤال: {query}")

    # 3) stream the single generation
    import time as _t
    t0 = _t.time()
    log.info("LLM    request  backend=%s channel=%s social=%s ctx_chunks=%d q=%r",
             CFG.llm.backend, channel, social, len(hits), (query or "")[:70])
    parts: list[str] = []
    ttft = None
    async for tok in llm.astream_tokens(system, history, user_msg):
        if not parts:
            qlog.mark_first_token()
            ttft = _t.time() - t0
            log.info("LLM    TTFT     %.2fs", ttft)
        parts.append(tok)
        yield {"type": "token", "text": tok}
    log.info("LLM    done     chunks=%d chars=%d total=%.2fs ttft=%.2fs",
             len(parts), sum(len(p) for p in parts), _t.time() - t0, ttft or 0)

    answer = "".join(parts).strip()
    # dense scores don't separate on/off-topic well for short Arabic, so trust the
    # LLM's grounded refusal: if it declined, mark refused and drop the doc cards.
    refused = (not social) and (not memory) and ((not hits) or _looks_refusal(answer))
    shown = [] if refused else _public_docs(hits)
    qlog.set_events(events)
    qlog.set_retrieved([] if refused else hits)
    rec = qlog.finish(answer, refused=refused)
    yield {"type": "done", "answer": answer, "refused": refused,
           "retrieved": shown, "events": events, "log_id": rec["id"]}


_REFUSAL_HINTS = ("آسف", "اسف", "مش قادر", "مقدرش", "مش موجود", "خارج نطاق", "لا يمكنني",
                  "لا أستطيع", "مفيش معلومات", "لا تتوفر", "متأسف", "أعتذر", "اعتذر")


def _looks_refusal(answer: str) -> bool:
    a = (answer or "")[:160]
    return any(h in a for h in _REFUSAL_HINTS)


def answer_once(query: str, history: list[dict] | None = None, channel: str = "chat") -> dict:
    import asyncio

    async def _run():
        out = None
        async for ev in stream_answer(query, history, channel):
            if ev["type"] == "done":
                out = ev
        return out
    return asyncio.run(_run())
