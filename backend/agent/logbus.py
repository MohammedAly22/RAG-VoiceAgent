"""Structured per-query logging.

Every chat/voice turn writes one JSON record to data/logs/queries.jsonl and a
pretty per-entry file under data/logs/entries/<id>.json. The Logs tab reads these
to show the full trace: user query, tool calls, retrieved chunks, the agent's
answer, backend used, and timings.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CFG, abspath  # noqa: E402

_DIR = Path(abspath(CFG.logging.logs_dir))
_ENTRIES = _DIR / "entries"
_JSONL = _DIR / "queries.jsonl"


def _ensure() -> None:
    _ENTRIES.mkdir(parents=True, exist_ok=True)


class QueryLog:
    """Accumulates one turn's trace; call .finish(answer) to persist."""

    def __init__(self, query: str, channel: str = "chat") -> None:
        self.id = uuid.uuid4().hex[:12]
        self.t0 = time.time()
        self.rec = {
            "id": self.id,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "channel": channel,          # chat | voice | livekit
            "query": query,
            "backend": CFG.llm.backend,
            "agent": CFG.agent.name,
            "events": [],                # tool calls, no_context, etc.
            "retrieved": [],             # retrieved chunks (with scores + sources)
            "answer": "",
            "refused": False,
            "first_token_ms": None,
            "total_ms": None,
        }

    def mark_first_token(self) -> None:
        if self.rec["first_token_ms"] is None:
            self.rec["first_token_ms"] = int((time.time() - self.t0) * 1000)

    def set_events(self, events: list) -> None:
        self.rec["events"] = events

    def set_retrieved(self, chunks: list) -> None:
        # keep it light: drop nothing but cap text length for the log
        self.rec["retrieved"] = [{
            "source": c.get("source"), "page": c.get("page"),
            "type": c.get("type"), "score": c.get("score"),
            "page_image": c.get("page_image"),
            "text": (c.get("text") or "")[:600],
        } for c in chunks]

    def finish(self, answer: str, refused: bool = False) -> dict:
        _ensure()
        self.rec["answer"] = answer
        self.rec["refused"] = refused
        self.rec["total_ms"] = int((time.time() - self.t0) * 1000)
        with open(_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(self.rec, ensure_ascii=False) + "\n")
        (_ENTRIES / f"{self.id}.json").write_text(
            json.dumps(self.rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.rec


def list_logs(limit: int = 100) -> list[dict]:
    if not _JSONL.exists():
        return []
    lines = _JSONL.read_text(encoding="utf-8").splitlines()
    out = []
    for ln in lines[-limit:][::-1]:
        try:
            r = json.loads(ln)
            out.append({k: r.get(k) for k in
                        ("id", "ts", "channel", "query", "answer", "backend",
                         "refused", "first_token_ms", "total_ms")})
        except Exception:  # noqa: BLE001
            continue
    return out


def get_log(entry_id: str) -> dict | None:
    p = _ENTRIES / f"{entry_id}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None
