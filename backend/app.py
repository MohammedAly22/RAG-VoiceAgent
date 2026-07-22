"""Voice Agent — FastAPI application.

Serves the React UI and the whole API surface:

  GET   /api/health
  GET   /api/config                      public config (agent, categories, backends)
  POST  /api/config                      save agent setup / settings (persists config.yaml)
  POST  /api/persona/suggest             LLM-generate a system prompt (Other category)
  WS    /api/chat                        streaming chat: token / tool_call / retrieved / done
  GET   /api/data                        list ingested sources
  POST  /api/data/upload                 upload + ingest a document (multipart)
  DELETE/api/data/{source}               remove a source from the vector store
  GET   /api/logs        /api/logs/{id}  query logs (Logs tab)
  GET   /api/pages/{path}                retrieved page screenshots
  POST  /api/asr                         proxy → ASR service (browser voice input)
  GET   /api/voices  ·  POST /api/tts    proxy → TTS service (browser voice output)
"""
from __future__ import annotations

import asyncio
import json
import time
import logging
import os
import re
import shutil
import sys
from pathlib import Path

import requests
from fastapi import (FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File,
                     HTTPException, Body)
from fastapi.responses import Response, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as cfgmod  # noqa: E402
import db  # noqa: E402
from config import CFG, abspath  # noqa: E402
from agent import graph as agentgraph  # noqa: E402
from agent import personas  # noqa: E402
from agent import logbus  # noqa: E402
from rag.store import get_store, reload_store  # noqa: E402
from rag.ingest import ingest_file  # noqa: E402

from logging_setup import setup as _setup_logging, preview  # noqa: E402

log = _setup_logging("app", "APP", CFG.logging.level)

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = Path(abspath("data/uploads"))
RECORDINGS = Path(abspath("data/recordings"))
PAGES = Path(abspath(CFG.rag.pages_dir))
DIST = ROOT / "frontend-react" / "dist"

app = FastAPI(title="Voice Agent")


@app.on_event("startup")
async def _startup():
    import asyncio
    # The knowledge base starts EMPTY — the user uploads their own documents during
    # the Setup wizard (or the Data tab). We only warm the embedder + LLM here.
    asyncio.get_event_loop().run_in_executor(None, agentgraph.warmup)


# ---------------------------------------------------------------------------
# meta / config
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "app": CFG.system.app_name, "backend": CFG.llm.backend}


@app.get("/api/config")
def get_config():
    c = cfgmod.CFG
    return {
        "app_name": c.system.app_name,
        "brand": c.system.brand,
        "language": c.system.language,
        "agent": dict(c.agent),
        "categories": [dict(x) for x in c.categories],
        "llm": {"backend": c.llm.backend,
                "gemini_model": c.llm.gemini.model,
                "vllm_model": c.llm.vllm.model_path},
        "tts": {"engine": c.tts.engine, "active_voice": c.tts.active_voice},
        "asr": {"provider": getattr(c.asr, "provider", "qwencleo"),
                "model": c.asr.model_id, "gemini_model": getattr(c.asr, "gemini_model", "gemini-2.5-flash")},
        "rag": {"embedding_model": c.rag.embedding_model,
                "vector_store": c.rag.vector_store,
                "top_k": c.rag.top_k, "score_threshold": c.rag.score_threshold,
                "multimodal": c.rag.multimodal},
        "services": _service_health(),
    }


@app.post("/api/config")
def save_config(payload: dict = Body(...)):
    """Persist agent setup / settings changes. Accepts partial {agent:{...},
    llm:{...}, tts:{...}} and rewrites config.yaml, then invalidates the agent."""
    allowed = {k: payload[k] for k in ("agent", "llm", "tts", "asr", "rag")
               if k in payload}
    cfgmod.save(allowed)
    agentgraph.invalidate()
    log.info("config saved: %s", list(allowed.keys()))
    return {"ok": True, "config": get_config()}


@app.post("/api/persona/suggest")
def persona_suggest(payload: dict = Body(...)):
    desc = (payload.get("description") or "").strip()
    name = (payload.get("name") or "").strip()
    if not desc:
        raise HTTPException(400, "description required")
    try:
        prompt = personas.suggest_prompt(desc, name)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"LLM error: {e}")
    return {"prompt": prompt}


# ---------------------------------------------------------------------------
# chat (streaming over WebSocket)
# ---------------------------------------------------------------------------
@app.websocket("/api/chat")
async def chat_ws(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            req = await ws.receive_json()
            query = (req.get("query") or "").strip()
            history = req.get("history") or []
            channel = req.get("channel") or "chat"
            session_id = req.get("session_id")
            if not query:
                await ws.send_json({"type": "error", "message": "empty query"})
                continue
            try:
                docs, tools = [], []
                async for ev in agentgraph.stream_answer(query, history, channel):
                    if ev["type"] == "tool_call":
                        tools.append(ev.get("tool"))
                    elif ev["type"] == "retrieved":
                        docs = ev.get("docs", [])
                    elif ev["type"] == "done":
                        # Persist BEFORE forwarding `done`: the browser closes the
                        # socket the instant it receives it, which cancels this
                        # handler — so the after-loop write never ran (0-message
                        # sessions). Writing here guarantees the turn is saved.
                        if session_id and channel == "chat":
                            db.add_message(session_id, "user", query)
                            db.add_message(session_id, "assistant", ev.get("answer", ""),
                                           docs=ev.get("retrieved", docs), tools=tools,
                                           refused=ev.get("refused", False))
                    await ws.send_json(ev)
            except WebSocketDisconnect:
                raise
            except Exception as e:  # noqa: BLE001
                log.exception("chat error")
                try:
                    await ws.send_json({"type": "error", "message": str(e)})
                except Exception:  # noqa: BLE001
                    pass
    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# sessions (chat history) + calls (voice history) + stats  → Dashboard
# ---------------------------------------------------------------------------
@app.get("/api/sessions")
def sessions_list():
    return {"sessions": db.list_sessions()}


@app.post("/api/sessions")
def sessions_create(payload: dict = Body(default={})):
    sid = db.create_session(payload.get("title") or "محادثة جديدة")
    return {"id": sid}


@app.get("/api/sessions/{sid}")
def sessions_get(sid: str):
    s = db.get_session(sid)
    if not s:
        raise HTTPException(404, "not found")
    return s


@app.patch("/api/sessions/{sid}")
def sessions_rename(sid: str, payload: dict = Body(...)):
    db.rename_session(sid, (payload.get("title") or "").strip() or "محادثة")
    return {"ok": True}


@app.delete("/api/sessions/{sid}")
def sessions_delete(sid: str):
    db.delete_session(sid)
    return {"ok": True}


@app.get("/api/calls")
def calls_list():
    return {"calls": db.list_calls()}


@app.get("/api/calls/{cid}")
def calls_get(cid: str):
    c = db.get_call(cid)
    if not c:
        raise HTTPException(404, "not found")
    return c


@app.post("/api/calls")
def calls_create(payload: dict = Body(...)):
    cid = db.create_call(
        title=payload.get("title") or "مكالمة صوتية",
        transcript=payload.get("transcript") or [],
        duration_sec=payload.get("duration_sec") or 0,
        summary=payload.get("summary") or "",
        outcome=payload.get("outcome") or "DONE")
    return {"id": cid}


@app.post("/api/calls/{cid}/audio")
async def calls_audio_upload(cid: str, file: UploadFile = File(...)):
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    ext = (file.filename or "rec.webm").rsplit(".", 1)[-1]
    dest = RECORDINGS / f"{cid}.{ext}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    db.set_call_audio(cid, f"{cid}.{ext}")
    return {"ok": True}


@app.get("/api/calls/{cid}/audio")
def calls_audio(cid: str):
    c = db.get_call(cid)
    if not c or not c.get("audio_path"):
        raise HTTPException(404, "no recording")
    p = RECORDINGS / c["audio_path"]
    if not p.exists():
        raise HTTPException(404, "file missing")
    return FileResponse(p)


@app.delete("/api/calls/{cid}")
def calls_delete(cid: str):
    ap = db.delete_call(cid)
    if ap:
        (RECORDINGS / ap).unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/stats")
def stats():
    st = db.stats()
    store = get_store()
    st["kb_docs"] = len(store.sources())
    st["kb_chunks"] = store.count()
    st["services"] = _service_health()
    return st


# ---------------------------------------------------------------------------
# data management
# ---------------------------------------------------------------------------
@app.get("/api/data")
def data_list():
    store = get_store()
    return {"sources": store.sources(), "total_chunks": store.count()}


@app.post("/api/data/upload")
async def data_upload(file: UploadFile = File(...)):
    UPLOADS.mkdir(parents=True, exist_ok=True)
    dest = UPLOADS / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        n = ingest_file(dest)
    except Exception as e:  # noqa: BLE001
        log.exception("ingest failed")
        raise HTTPException(500, f"ingest failed: {e}")
    return {"ok": True, "source": file.filename, "chunks": n,
            "sources": get_store().sources()}


@app.delete("/api/data/{source}")
def data_delete(source: str):
    removed = get_store().remove_source(source)
    up = UPLOADS / source
    if up.exists():
        up.unlink()
    return {"ok": True, "removed": removed, "sources": get_store().sources()}


@app.post("/api/data/reindex")
def data_reindex():
    reload_store()
    return {"ok": True, "sources": get_store().sources(),
            "total_chunks": get_store().count()}


@app.get("/api/data/{source}/chunks")
def data_chunks(source: str):
    """All chunks for one source (for the Data-tab file viewer + in-doc search)."""
    store = get_store()
    chunks = [{"id": c.get("id"), "text": c.get("text"), "page": c.get("page"),
               "type": c.get("type"), "page_image": c.get("page_image")}
              for c in store.chunks if c.get("source") == source]
    # page screenshots available for this source (PDF viewer)
    pages = sorted({c["page_image"] for c in chunks if c.get("page_image")})
    return {"source": source, "chunks": chunks, "pages": pages,
            "kind": _file_kind(source)}


@app.get("/api/data/{source}/file")
def data_file(source: str):
    """Serve the raw uploaded/seed file so the UI can render it in a viewer."""
    for base in (UPLOADS, Path(abspath("data/kb"))):
        p = base / source
        if p.exists() and str(p.resolve()).startswith(str(base.resolve())):
            return FileResponse(p)
    raise HTTPException(404, "file not found")


@app.get("/api/search")
def kb_search(q: str, k: int = 8):
    """Semantic/hybrid search across the whole knowledge base (Data-tab search)."""
    if not q.strip():
        return {"results": []}
    hits = get_store().search(q, top_k=k)
    return {"results": [{
        "source": h.get("source"), "page": h.get("page"), "type": h.get("type"),
        "score": h.get("score"), "page_image": h.get("page_image"),
        "snippet": (h.get("text") or "")[:300]} for h in hits]}


def _file_kind(name: str) -> str:
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext == "pdf":
        return "pdf"
    if ext in ("png", "jpg", "jpeg", "gif", "webp"):
        return "image"
    if ext == "docx":
        return "docx"
    return "text"


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------
@app.get("/api/logs")
def logs_list(limit: int = 100):
    return {"logs": logbus.list_logs(limit)}


@app.get("/api/logs/{entry_id}")
def logs_get(entry_id: str):
    r = logbus.get_log(entry_id)
    if not r:
        raise HTTPException(404, "not found")
    return r


@app.get("/api/pages/{path:path}")
def page_image(path: str):
    p = PAGES / path
    if not p.exists() or not str(p.resolve()).startswith(str(PAGES.resolve())):
        raise HTTPException(404, "not found")
    return FileResponse(p)


# ---------------------------------------------------------------------------
# voice proxies (ASR / TTS services — optional, may be down)
# ---------------------------------------------------------------------------
# Citations/markdown must never reach the TTS (they'd be read out loud).
_CITE_RE = re.compile(r"\((?:المصدر|المصادر|Source)\s*:[^)]*\)")


# Arabic-Indic (٠-٩) and Extended (۰-۹) digits → ASCII, so TTS reads them correctly.
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def clean_for_speech(text: str) -> str:
    t = _CITE_RE.sub("", text or "")
    t = re.sub(r"\[\d+\]", "", t)
    t = re.sub(r"[^\s]+\.(?:md|pdf|docx|txt)", "", t)
    t = re.sub(r"[*_`#>]+", "", t)
    t = t.translate(_AR_DIGITS)
    t = re.sub(r"\s*\n\s*", " ، ", t)
    return re.sub(r"\s{2,}", " ", t).strip(" ،-–—:")


def _asr_url() -> str:
    return f"http://{CFG.asr.host}:{CFG.asr.port}"


def _tts_url() -> str:
    return f"http://{CFG.tts.host}:{CFG.tts.port}"


async def _eou_check(text: str) -> dict | None:
    """Ask the EoU service whether a finalized utterance is a complete turn.
    Populates eou.log with a real decision on every voice utterance."""
    text = (text or "").strip()
    if not text or not CFG.eou.enabled:
        return None
    try:
        r = await asyncio.to_thread(
            requests.post, f"http://{CFG.eou.host}:{CFG.eou.port}/eou",
            json={"text": text, "language": CFG.eou.language}, timeout=3)
        r.raise_for_status()
        d = r.json()
        log.info("EoU    check    complete=%s prob=%.2f text=%r", d.get("complete"), d.get("prob", 0), preview(text, 50))
        return d
    except Exception as e:  # noqa: BLE001
        log.warning("EoU    check failed: %s", e)
        return None


def _eou_log_bg(text: str) -> None:
    """Fire-and-forget EoU check — keeps eou.log populated without adding a
    round-trip to the ASR→LLM critical path."""
    try:
        asyncio.create_task(_eou_check(text))
    except RuntimeError:
        pass


def _merge_segment(acc: str, nxt: str) -> str:
    """Server-side twin of the client's appendSegment: merge a rolling-window ASR
    segment into the running utterance, dropping the overlap. Lets QwenCleo emit a
    *cumulative* per-utterance transcript (same contract as Gemini)."""
    t = (nxt or "").strip()
    if not t:
        return acc
    if not acc:
        return t
    if acc.endswith(t):
        return acc
    if t.startswith(acc):
        return t
    words = acc.split()
    for n in range(min(8, len(words)), 0, -1):
        tail = " ".join(words[-n:])
        if t.startswith(tail):
            return (acc + t[len(tail):]).strip()
    return acc + " " + t


@app.post("/api/asr")
async def asr_proxy(file: UploadFile = File(...)):
    import base64
    raw = await file.read()
    if CFG.asr.provider == "gemini":
        import numpy as np, soundfile as sf, io as _io
        try:
            data, sr = sf.read(_io.BytesIO(raw), dtype="float32")
            if getattr(data, "ndim", 1) > 1:
                data = data[:, 0]
            from asr_gemini import atranscribe
            text = await atranscribe(np.asarray(data), int(sr), CFG.asr.gemini_model)
            log.info("ASR-GEM oneshot text=%r", preview(text))
            return {"text": text}
        except Exception as e:  # noqa: BLE001
            log.warning("ASR-GEM failed: %s", e)
            raise HTTPException(503, f"Gemini ASR error: {e}")
    try:
        r = requests.post(f"{_asr_url()}/transcribe",
                          json={"audio_b64": base64.b64encode(raw).decode()},
                          timeout=60)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"ASR service unavailable: {e}")
    return r.json()


@app.websocket("/api/asr/stream")
async def asr_stream_proxy(ws: WebSocket):
    """Relay browser mic audio → ASR (QwenCleo service or Gemini) → live partials.

    The browser sends float32 PCM @16k binary frames and the text "flush" to force
    a final transcript. On each final we consult the EoU service (logged) and pass
    the decision to the client. Provider is `asr.provider` in config.
    """
    await ws.accept()
    if CFG.asr.provider == "gemini":
        await _asr_stream_gemini(ws)
    else:
        await _asr_stream_qwencleo(ws)


async def _asr_stream_qwencleo(ws: WebSocket):
    import websockets as wsclient
    url = f"ws://{CFG.asr.host}:{CFG.asr.port}/ws/stream"
    log.info("ASR-WS open     proxy → %s (qwencleo)", url)
    t0 = time.time(); frames = 0; partials = 0
    try:
        async with wsclient.connect(url, max_size=None) as up:
            async def pump_up():
                nonlocal frames
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        return
                    if msg.get("bytes") is not None:
                        frames += 1
                        await up.send(msg["bytes"])
                    elif msg.get("text"):
                        await up.send(msg["text"])
                        if msg["text"] == "close":
                            return

            async def pump_down():
                nonlocal partials
                utt = ""      # cumulative transcript of the current utterance
                async for raw in up:
                    partials += 1
                    if partials == 1:
                        log.info("ASR-WS first    partial after %.2fs", time.time() - t0)
                    if isinstance(raw, str):
                        try:
                            d = json.loads(raw)
                        except Exception:  # noqa: BLE001
                            d = None
                        if d is not None and "text" in d:
                            utt = _merge_segment(utt, d.get("text", ""))
                            is_final = bool(d.get("is_final"))
                            await ws.send_text(json.dumps(
                                {"text": utt, "is_final": is_final, "cumulative": True},
                                ensure_ascii=False))
                            if is_final:
                                _eou_log_bg(utt)
                                utt = ""
                            continue
                    await ws.send_text(raw if isinstance(raw, str) else raw.decode())

            tasks = [asyncio.create_task(pump_up()), asyncio.create_task(pump_down())]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("ASR-WS error: %s", e)
    log.info("ASR-WS closed   frames=%d partials=%d elapsed=%.1fs", frames, partials, time.time() - t0)


async def _asr_stream_gemini(ws: WebSocket):
    """Gemini streaming ASR: accumulate VAD-gated speech, re-transcribe the rolling
    buffer for partials, and finalize on flush (with an EoU check)."""
    import numpy as np
    from asr_gemini import GeminiStreamSession
    sess = GeminiStreamSession(int(CFG.asr.sample_rate), CFG.asr.gemini_model)
    # One-shot mode (chat voice messages): accumulate ALL the speech and transcribe
    # it in a SINGLE call on flush — no incremental partials. Streaming Gemini
    # re-transcription of a growing buffer is what caused hallucinations, so for
    # Gemini we never stream; we transcribe the whole utterance once it's complete.
    oneshot = False
    log.info("ASR-GEM open     stream (model=%s)", CFG.asr.gemini_model)
    t0 = time.time(); frames = 0
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                sess.add(np.frombuffer(msg["bytes"], dtype=np.float32))
                frames += 1
                if not oneshot:
                    part = await sess.maybe_partial()
                    if part:
                        # `cumulative`: FULL transcript of the utterance so far —
                        # the client replaces, it does not append.
                        await ws.send_text(json.dumps(
                            {"text": part, "is_final": False, "cumulative": True}, ensure_ascii=False))
            elif msg.get("text") == "oneshot":
                oneshot = True
                log.info("ASR-GEM mode     one-shot (no streaming, single transcription on flush)")
            elif msg.get("text") == "flush":
                final = await sess.final()
                # Always send a final (even empty) so a one-shot client never hangs.
                await ws.send_text(json.dumps(
                    {"text": final, "is_final": True, "cumulative": True}, ensure_ascii=False))
                if final:
                    _eou_log_bg(final)      # EoU is informational → off the critical path
            elif msg.get("text") == "close":
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("ASR-GEM error: %s", e)
    log.info("ASR-GEM closed   frames=%d elapsed=%.1fs", frames, time.time() - t0)


@app.websocket("/api/tts/stream")
async def tts_stream_proxy(ws: WebSocket):
    """Relay text → TTS service WS → PCM chunks back, so playback can start on
    the first sentence (low time-to-first-audio) instead of waiting for the
    whole utterance to synthesize."""
    import websockets as wsclient
    await ws.accept()
    url = f"ws://{CFG.tts.host}:{CFG.tts.port}/ws/stream"
    log.info("TTS-WS open     proxy → %s", url)
    try:
        async with wsclient.connect(url, max_size=None) as up:
            while True:
                req = await ws.receive_json()
                text = (req.get("text") or "").strip()
                if not text:
                    continue
                log.info("TTS-WS request  chars=%d voice=%s text=%r",
                         len(text), req.get("voice") or CFG.tts.active_voice, preview(text))
                t0 = time.time(); first = None; chunks = 0
                await up.send(json.dumps({"text": text, "voice": req.get("voice")}))
                while True:
                    raw = await up.recv()
                    if isinstance(raw, bytes):
                        chunks += 1
                        if first is None:
                            first = time.time() - t0
                            log.info("TTS-WS TTFA     %.2fs", first)
                        await ws.send_bytes(raw)
                    else:
                        ev = json.loads(raw)
                        if ev.get("event") == "end":
                            log.info("TTS-WS done     chunks=%d gen=%.2fs ttfa=%.2fs",
                                     chunks, time.time() - t0, first or 0)
                            await ws.send_json({**ev, "ttfa": round(first or 0, 3)})
                            break
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("TTS-WS error: %s", e)
    log.info("TTS-WS closed")


@app.get("/api/voices/{name}/audio")
def voice_sample(name: str):
    """Serve a speaker's reference clip — instant preview, no synthesis needed."""
    try:
        r = requests.get(f"{_tts_url()}/speakers/{name}/audio", timeout=15)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"TTS service unavailable: {e}")
    return Response(content=r.content, media_type="audio/wav")


@app.get("/api/voices")
def voices():
    try:
        r = requests.get(f"{_tts_url()}/speakers", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"TTS service unavailable: {e}")


@app.post("/api/tts")
def tts_proxy(payload: dict = Body(...)):
    text = clean_for_speech(payload.get("text", ""))
    log.info("TTS    request  chars=%d voice=%s text=%r", len(text),
             payload.get("voice") or CFG.tts.active_voice, preview(text))
    t0 = time.time()
    try:
        r = requests.post(f"{_tts_url()}/synthesize",
                          json={"text": text, "voice": payload.get("voice")},
                          timeout=120)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        log.warning("TTS    failed   %s", e)
        raise HTTPException(503, f"TTS service unavailable: {e}")
    log.info("TTS    done     took=%.2fs bytes=%d", time.time() - t0, len(r.content))
    return Response(content=r.content, media_type="audio/wav")


@app.get("/api/livekit/token")
def livekit_token(identity: str = "user", room: str | None = None):
    """Mint a LiveKit access token so the browser can join a room. The agent
    worker (scripts/start_livekit_agent.sh) auto-dispatches into the room."""
    key = os.environ.get("LIVEKIT_API_KEY")
    secret = os.environ.get("LIVEKIT_API_SECRET")
    url = os.environ.get("LIVEKIT_URL", CFG.livekit.url)
    if not key or not secret:
        raise HTTPException(503, "LIVEKIT_API_KEY/SECRET not set")
    room = room or (CFG.livekit.room_prefix + "session")
    try:
        from livekit import api as lkapi
        token = (lkapi.AccessToken(key, secret)
                 .with_identity(identity)
                 .with_name(identity)
                 .with_grants(lkapi.VideoGrants(room_join=True, room=room))
                 .to_jwt())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"token error: {e}")
    return {"token": token, "url": url, "room": room}


def _service_health() -> dict:
    out = {}
    for name, url in (("asr", f"{_asr_url()}/health"),
                      ("tts", f"{_tts_url()}/health"),
                      ("eou", f"http://{CFG.eou.host}:{CFG.eou.port}/health")):
        try:
            requests.get(url, timeout=1.5).raise_for_status()
            out[name] = True
        except Exception:  # noqa: BLE001
            out[name] = False
    # Gemini ASR runs inside the app (no separate QwenCleo service / no VRAM), so
    # voice is available even when the ASR service isn't started.
    if CFG.asr.provider == "gemini":
        out["asr"] = True
    return out


# ---------------------------------------------------------------------------
# static UI (mounted last so /api/* wins)
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    idx = DIST / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return JSONResponse({"message": "UI not built yet. Run scripts/build_ui.sh, "
                         "or use the API at /api/*."})


if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="ui")
