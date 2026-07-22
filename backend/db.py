"""SQLite persistence for chat sessions and voice calls.

Keeps the conversation history (so sessions survive reloads) and a structured
record of every voice call (transcript + recorded audio + summary), surfaced in
the Dashboard and in per-item detail views.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import CFG, abspath  # noqa: E402

_DB = Path(abspath("./data/voiceagent.sqlite"))
_DB.parent.mkdir(parents=True, exist_ok=True)
_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, title TEXT, created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,
  docs TEXT, tools TEXT, refused INTEGER, created_at REAL,
  FOREIGN KEY(session_id) REFERENCES sessions(id)
);
CREATE TABLE IF NOT EXISTS calls (
  id TEXT PRIMARY KEY, title TEXT, created_at REAL, duration_sec REAL,
  audio_path TEXT, summary TEXT, transcript TEXT, outcome TEXT, turns INTEGER
);
CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _LOCK, _conn() as c:
        c.executescript(_SCHEMA)


def _now() -> float:
    return time.time()


# ---- sessions --------------------------------------------------------------
def create_session(title: str = "محادثة جديدة") -> str:
    sid = "s_" + uuid.uuid4().hex[:12]
    with _LOCK, _conn() as c:
        c.execute("INSERT INTO sessions(id,title,created_at,updated_at) VALUES(?,?,?,?)",
                  (sid, title, _now(), _now()))
    return sid


def list_sessions(limit: int = 200) -> list[dict]:
    with _conn() as c:
        rows = c.execute("""
          SELECT s.id, s.title, s.created_at, s.updated_at,
                 (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS n,
                 (SELECT content FROM messages m WHERE m.session_id=s.id ORDER BY created_at DESC LIMIT 1) AS last
          FROM sessions s ORDER BY s.updated_at DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_session(sid: str) -> dict | None:
    with _conn() as c:
        s = c.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        if not s:
            return None
        msgs = c.execute("SELECT * FROM messages WHERE session_id=? ORDER BY created_at", (sid,)).fetchall()
    return {"session": dict(s), "messages": [_msg_out(m) for m in msgs]}


def rename_session(sid: str, title: str) -> None:
    with _LOCK, _conn() as c:
        c.execute("UPDATE sessions SET title=?, updated_at=? WHERE id=?", (title, _now(), sid))


def delete_session(sid: str) -> None:
    with _LOCK, _conn() as c:
        c.execute("DELETE FROM messages WHERE session_id=?", (sid,))
        c.execute("DELETE FROM sessions WHERE id=?", (sid,))


def add_message(sid: str, role: str, content: str, docs=None, tools=None, refused=False) -> None:
    mid = "m_" + uuid.uuid4().hex[:12]
    with _LOCK, _conn() as c:
        c.execute("""INSERT INTO messages(id,session_id,role,content,docs,tools,refused,created_at)
                     VALUES(?,?,?,?,?,?,?,?)""",
                  (mid, sid, role, content, json.dumps(docs or [], ensure_ascii=False),
                   json.dumps(tools or [], ensure_ascii=False), 1 if refused else 0, _now()))
        c.execute("UPDATE sessions SET updated_at=? WHERE id=?", (_now(), sid))
        # auto-title from the first user message
        row = c.execute("SELECT title FROM sessions WHERE id=?", (sid,)).fetchone()
        if role == "user" and row and row["title"] in ("محادثة جديدة", "", None):
            c.execute("UPDATE sessions SET title=? WHERE id=?", (content[:40], sid))


def _msg_out(m: sqlite3.Row) -> dict:
    return {"id": m["id"], "role": m["role"], "content": m["content"],
            "docs": json.loads(m["docs"] or "[]"), "tools": json.loads(m["tools"] or "[]"),
            "refused": bool(m["refused"]), "created_at": m["created_at"]}


# ---- calls -----------------------------------------------------------------
def create_call(title: str, transcript: list, duration_sec: float,
                summary: str = "", outcome: str = "DONE", audio_path: str = "") -> str:
    cid = "c_" + uuid.uuid4().hex[:12]
    with _LOCK, _conn() as c:
        c.execute("""INSERT INTO calls(id,title,created_at,duration_sec,audio_path,summary,transcript,outcome,turns)
                     VALUES(?,?,?,?,?,?,?,?,?)""",
                  (cid, title, _now(), duration_sec, audio_path, summary,
                   json.dumps(transcript or [], ensure_ascii=False), outcome, len(transcript or [])))
    return cid


def set_call_audio(cid: str, audio_path: str) -> None:
    with _LOCK, _conn() as c:
        c.execute("UPDATE calls SET audio_path=? WHERE id=?", (audio_path, cid))


def list_calls(limit: int = 200) -> list[dict]:
    with _conn() as c:
        rows = c.execute("""SELECT id,title,created_at,duration_sec,summary,outcome,turns,
                            (audio_path IS NOT NULL AND audio_path!='') AS has_audio
                            FROM calls ORDER BY created_at DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_call(cid: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM calls WHERE id=?", (cid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["transcript"] = json.loads(d.get("transcript") or "[]")
    d["has_audio"] = bool(d.get("audio_path"))
    return d


def delete_call(cid: str) -> str | None:
    with _LOCK, _conn() as c:
        r = c.execute("SELECT audio_path FROM calls WHERE id=?", (cid,)).fetchone()
        c.execute("DELETE FROM calls WHERE id=?", (cid,))
    return r["audio_path"] if r else None


def stats() -> dict:
    with _conn() as c:
        s = c.execute("SELECT COUNT(*) n FROM sessions").fetchone()["n"]
        m = c.execute("SELECT COUNT(*) n FROM messages").fetchone()["n"]
        cl = c.execute("SELECT COUNT(*) n FROM calls").fetchone()["n"]
    return {"sessions": s, "messages": m, "calls": cl}


init()
