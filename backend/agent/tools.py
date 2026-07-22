"""Agent tools (LangChain @tool) — what the LLM can call mid-conversation.

- `retrieve_kb(query)`  — the RAG retrieval tool. Searches the vector store and
  returns grounded context with inline citations, OR the sentinel
  `NO_RELEVANT_CONTEXT` when the best hit is below `rag.score_threshold`
  (this is the anti-hallucination guardrail — the model is told to refuse).
- `get_order_status(order_id)` — a mocked lookup, mirroring the PDF's example of
  a second, safely-schema'd tool.

Because a tool's string return is what the LLM sees, we also record the raw
retrieved chunks into a request-scoped collector (contextvar) so the app can show
the retrieved documents / page screenshots in the UI and the logs.
"""
from __future__ import annotations

import contextvars
import sys
from pathlib import Path

from langchain_core.tools import tool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CFG  # noqa: E402
from rag.store import get_store  # noqa: E402

NO_CONTEXT = "NO_RELEVANT_CONTEXT"

# per-request collector of retrieved chunks + tool events (set by the app layer)
_retrieved: contextvars.ContextVar[list] = contextvars.ContextVar("retrieved", default=None)
_events: contextvars.ContextVar[list] = contextvars.ContextVar("events", default=None)


def new_request_context() -> tuple[list, list]:
    """Call at the start of each request; returns (retrieved_list, events_list)
    that the tools will populate."""
    retrieved: list = []
    events: list = []
    _retrieved.set(retrieved)
    _events.set(events)
    return retrieved, events


def _record_retrieved(chunks: list) -> None:
    box = _retrieved.get()
    if box is not None:
        box.extend(chunks)


def _record_event(ev: dict) -> None:
    box = _events.get()
    if box is not None:
        box.append(ev)


@tool
def retrieve_kb(query: str) -> str:
    """ابحث في قاعدة المعرفة (المستندات المرفوعة) عن معلومات تخص سؤال المستخدم.
    استخدم هذه الأداة دائماً قبل الإجابة على أي سؤال معلوماتي عن المطعم/الجهة.
    Search the knowledge base for information relevant to the user's question."""
    store = get_store()
    hits = store.search(query, top_k=CFG.rag.top_k)
    _record_event({"type": "tool_call", "tool": "retrieve_kb", "query": query,
                   "n_results": len(hits)})
    if not hits or hits[0]["score"] < CFG.rag.score_threshold:
        _record_event({"type": "no_context", "top_score": hits[0]["score"] if hits else 0.0})
        return NO_CONTEXT
    _record_retrieved(hits)
    # format grounded context with citation markers [source p.N]
    blocks = []
    for i, h in enumerate(hits, 1):
        cite = h["source"] + (f" ص{h['page']}" if h.get("page") else "")
        blocks.append(f"[{i}] (المصدر: {cite})\n{h['text']}")
    return "معلومات من قاعدة المعرفة:\n\n" + "\n\n---\n\n".join(blocks)


@tool
def get_order_status(order_id: str) -> str:
    """اعرف حالة طلب دليفري بواسطة رقم الطلب. Look up the status of a delivery order
    by its order id. Returns a mocked status for demo purposes."""
    _record_event({"type": "tool_call", "tool": "get_order_status", "order_id": order_id})
    # mocked lookup (as in the PDF example)
    demo = {
        "1001": "الطلب رقم ١٠٠١ اتأكد وهو دلوقتي في المطبخ، هيوصل خلال ٤٠ دقيقة.",
        "1002": "الطلب رقم ١٠٠٢ خرج مع الدليفري، هيوصل خلال ١٠ دقايق.",
        "1003": "الطلب رقم ١٠٠٣ اتسلّم بنجاح. بالهنا والشفا!",
    }
    return demo.get(order_id.strip(),
                    f"معلش، مفيش طلب بالرقم {order_id}. اتأكد من الرقم من فضلك.")


ALL_TOOLS = [retrieve_kb, get_order_status]
