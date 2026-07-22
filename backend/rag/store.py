"""Vector store for the RAG pipeline.

FAISS dense index (cosine via normalized inner-product) over multilingual-e5
embeddings, optionally fused with a BM25 sparse score (hybrid retrieval).

A "chunk" is a dict:
    {
      "id":         "<uuid>",
      "text":       "<chunk text>",
      "source":     "menu.pdf",
      "page":       3,                 # 1-indexed, or None
      "chunk_index": 0,
      "type":       "text" | "table" | "image_caption",
      "page_image": "menu.pdf/p3.png"  # relative to rag.pages_dir, or None
    }

Persistence (under rag.index_dir):
    index.faiss     — the FAISS index
    chunks.json     — the list of chunk dicts (row i ↔ index row i)
    meta.json       — {embedding_model, dim, count}
"""
from __future__ import annotations

import json
import logging
import sys
import threading
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CFG, abspath  # noqa: E402

log = logging.getLogger("rag.store")

_LOCK = threading.Lock()


class VectorStore:
    def __init__(self) -> None:
        self.cfg = CFG.rag
        self.dir = Path(abspath(self.cfg.index_dir))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.chunks: list[dict] = []
        self._index = None          # faiss index
        self._embedder = None       # SentenceTransformer
        self._dense_ok = None       # None=untried, True/False after load attempt
        self._bm25 = None           # rank_bm25.BM25Okapi
        self._dim: int | None = None
        self._load()

    # ---- embedding model (lazy, optional) ---------------------------------
    # If the embedding model can't be loaded (e.g. not downloaded yet), the store
    # degrades gracefully to BM25-only retrieval instead of hard-failing. Dense
    # FAISS retrieval activates automatically once the model is available and the
    # store is (re)indexed.
    @property
    def dense_available(self) -> bool:
        if self._dense_ok is None:
            self._try_load_embedder()
        return bool(self._dense_ok)

    def _try_load_embedder(self) -> None:
        # Load from the local HF cache only, so the store never blocks on a slow
        # or rate-limited network. Set VA_EMBED_ALLOW_DOWNLOAD=1 to permit a
        # deliberate online download (used by scripts/prepare_embedder).
        import os
        allow_dl = os.environ.get("VA_EMBED_ALLOW_DOWNLOAD") == "1"
        prev = os.environ.get("HF_HUB_OFFLINE")
        if not allow_dl:
            os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            from sentence_transformers import SentenceTransformer
            log.info("loading embedder %s on %s", self.cfg.embedding_model, self.cfg.embedding_device)
            self._embedder = SentenceTransformer(
                self.cfg.embedding_model, device=self.cfg.embedding_device)
            self._dense_ok = True
        except Exception as e:  # noqa: BLE001
            log.warning("embedder unavailable → BM25-only retrieval. (%s)", str(e)[:160])
            self._embedder = None
            self._dense_ok = False
        finally:
            if not allow_dl:
                if prev is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = prev

    def _embed(self, texts: list[str], *, is_query: bool) -> np.ndarray | None:
        if not self.dense_available:
            return None
        prefix = "query: " if is_query else "passage: "   # e5 prefix convention
        vecs = self._embedder.encode([prefix + t for t in texts],
                                     normalize_embeddings=True,
                                     convert_to_numpy=True,
                                     show_progress_bar=False)
        return vecs.astype("float32")

    # ---- persistence -------------------------------------------------------
    def _load(self) -> None:
        chk_path = self.dir / "chunks.json"
        if not chk_path.exists():
            log.info("no existing index at %s (empty store)", self.dir)
            return
        self.chunks = json.loads(chk_path.read_text(encoding="utf-8"))
        idx_path = self.dir / "index.faiss"
        if idx_path.exists():
            import faiss
            self._index = faiss.read_index(str(idx_path))
            self._dim = self._index.d
        self._rebuild_bm25()
        log.info("loaded vector store: %d chunks (dense=%s)",
                 len(self.chunks), self._index is not None)

    def _save(self) -> None:
        if self._index is not None:
            import faiss
            faiss.write_index(self._index, str(self.dir / "index.faiss"))
        else:
            # BM25-only: make sure a stale dense index isn't left behind
            (self.dir / "index.faiss").unlink(missing_ok=True)
        (self.dir / "chunks.json").write_text(
            json.dumps(self.chunks, ensure_ascii=False, indent=1), encoding="utf-8")
        (self.dir / "meta.json").write_text(json.dumps({
            "embedding_model": self.cfg.embedding_model if self._index is not None else None,
            "mode": "hybrid" if self._index is not None else "bm25-only",
            "dim": self._dim, "count": len(self.chunks),
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    def _rebuild_bm25(self) -> None:
        # Always build BM25 when there are chunks: it powers hybrid fusion *and*
        # is the fallback retriever when no dense index is available.
        if not self.chunks:
            self._bm25 = None
            return
        from rank_bm25 import BM25Okapi
        self._bm25 = BM25Okapi([_tokenize(c["text"]) for c in self.chunks])

    # ---- write path --------------------------------------------------------
    def add(self, new_chunks: list[dict]) -> int:
        if not new_chunks:
            return 0
        with _LOCK:
            self.chunks.extend(new_chunks)
            self._reindex_dense()
            self._rebuild_bm25()
            self._save()
        log.info("added %d chunks (total %d, dense=%s)",
                 len(new_chunks), len(self.chunks), self._index is not None)
        return len(new_chunks)

    def remove_source(self, source: str) -> int:
        """Drop every chunk from a given source file and rebuild the index."""
        with _LOCK:
            keep = [c for c in self.chunks if c.get("source") != source]
            removed = len(self.chunks) - len(keep)
            if removed == 0:
                return 0
            self.chunks = keep
            self._reindex_dense()
            self._rebuild_bm25()
            self._save()
        log.info("removed %d chunks from source=%s", removed, source)
        return removed

    def _reindex_dense(self) -> None:
        """Rebuild the FAISS index from all chunks if a dense embedder is
        available; otherwise leave it None (BM25-only mode)."""
        if not self.chunks or not self.dense_available:
            self._index = None
            self._dim = None
            return
        import faiss
        vecs = self._embed([c["text"] for c in self.chunks], is_query=False)
        self._dim = vecs.shape[1]
        self._index = faiss.IndexFlatIP(self._dim)
        self._index.add(vecs)

    # ---- read path ---------------------------------------------------------
    def search(self, query: str, top_k: int | None = None) -> list[dict]:
        """Return the top_k chunks (copies) each with a fused `score` in [0,1].

        Hybrid dense (FAISS) + sparse (BM25) when the embedder is available;
        BM25-only otherwise. Scores are normalized to [0,1] so `score_threshold`
        behaves consistently in both modes."""
        if not self.chunks:
            return []
        k = top_k or self.cfg.top_k
        n = len(self.chunks)

        dense: dict[int, float] = {}
        qv = self._embed([query], is_query=True) if self._index is not None else None
        if qv is not None:
            sims, idxs = self._index.search(qv, min(max(k * 3, k), n))
            dense = {int(i): (float(s) + 1.0) / 2.0 for s, i in zip(sims[0], idxs[0]) if i >= 0}

        sparse: dict[int, float] = {}
        if self._bm25 is not None:
            raw = self._bm25.get_scores(_tokenize(query))
            mx = float(raw.max()) if raw.size and raw.max() > 0 else 1.0
            sparse = {i: float(raw[i]) / mx for i in range(n)}

        if dense and sparse:
            fused = {i: 0.65 * dense.get(i, 0.0) + 0.35 * sparse.get(i, 0.0)
                     for i in set(dense) | set(sparse)}
        else:
            fused = dense or sparse

        ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
        out = []
        for i, score in ranked:
            c = dict(self.chunks[i])
            c["score"] = round(float(score), 4)
            out.append(c)
        return out

    # ---- introspection -----------------------------------------------------
    def sources(self) -> list[dict]:
        agg: dict[str, dict] = {}
        for c in self.chunks:
            s = c.get("source", "?")
            d = agg.setdefault(s, {"source": s, "chunks": 0, "pages": set(),
                                   "types": set()})
            d["chunks"] += 1
            if c.get("page"):
                d["pages"].add(c["page"])
            d["types"].add(c.get("type", "text"))
        return [{"source": d["source"], "chunks": d["chunks"],
                 "pages": len(d["pages"]), "types": sorted(d["types"])}
                for d in agg.values()]

    def count(self) -> int:
        return len(self.chunks)


def _tokenize(text: str) -> list[str]:
    # simple whitespace + strip Arabic tatweel/punct — good enough for BM25.
    import re
    text = re.sub(r"[ـ]", "", text)  # tatweel
    return re.findall(r"[\w؀-ۿ]+", text.lower())


# --- module-level singleton -------------------------------------------------
_STORE: VectorStore | None = None


def get_store() -> VectorStore:
    global _STORE
    if _STORE is None:
        _STORE = VectorStore()
    return _STORE


def reload_store() -> VectorStore:
    global _STORE
    _STORE = VectorStore()
    return _STORE
