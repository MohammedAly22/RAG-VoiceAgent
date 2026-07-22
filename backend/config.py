"""Central config loader for the Voice Agent.

Reads config.yaml once and exposes a dotted-access object so every service
(app / ASR / TTS / EoU / LLM / LiveKit worker) is driven by one source of truth.
Also loads .env (no extra dependency) and supports live re-save from the UI.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import yaml

# Project root = parent of backend/
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("VA_CONFIG", ROOT / "config.yaml"))
_LOCK = threading.Lock()


def _load_dotenv() -> None:
    """Minimal .env loader. Real environment wins, so `FOO=bar scripts/...`
    overrides .env."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv()


class DotDict(dict):
    """dict with recursive attribute access."""

    def __getattr__(self, k: str) -> Any:
        try:
            v = self[k]
        except KeyError as e:
            raise AttributeError(k) from e
        return DotDict(v) if isinstance(v, dict) else v

    def __setattr__(self, k: str, v: Any) -> None:
        self[k] = v


def _load() -> DotDict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return DotDict(raw)


CFG = _load()


def reload() -> DotDict:
    global CFG
    with _LOCK:
        CFG = _load()
    return CFG


def save(new_cfg: dict) -> DotDict:
    """Persist an updated config back to config.yaml (used by the UI Setup /
    Settings tabs). Merges shallowly at the top level, then rewrites the file."""
    global CFG
    with _LOCK:
        raw = _load()
        for k, v in new_cfg.items():
            if isinstance(v, dict) and isinstance(raw.get(k), dict):
                raw[k].update(v)
            else:
                raw[k] = v
        # dump plain dict (strip DotDict wrappers) preserving unicode/Arabic
        plain = _to_plain(raw)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(plain, f, allow_unicode=True, sort_keys=False, width=100)
        # Mutate the EXISTING CFG object in place so every module that did
        # `from config import CFG` sees the new values without a restart — this is
        # what makes the LLM/TTS/ASR hot-swap actually take effect app-wide.
        fresh = _load()
        CFG.clear()
        CFG.update(fresh)
    return CFG


def _to_plain(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    return obj


def abspath(rel: str) -> str:
    """Resolve a config path (relative to project root) to an absolute path."""
    p = Path(rel)
    return str(p if p.is_absolute() else (ROOT / p)).rstrip("/")


def category_by_id(cid: str) -> dict | None:
    for c in CFG.categories:
        if c["id"] == cid:
            return dict(c)
    return None


if __name__ == "__main__":
    print("Loaded config:", CONFIG_PATH)
    print("App:", CFG.system.app_name, "| LLM backend:", CFG.llm.backend)
    print("Agent:", CFG.agent.name, "| category:", CFG.agent.category)
    print("Embeddings:", CFG.rag.embedding_model, "| store:", CFG.rag.vector_store)
