"""Shared logging setup — detailed, file-backed logs for every service.

Each service writes to data/logs/<name>.log (rotating) *and* stdout, with a
consistent format that includes the service tag, level and timestamp. Services
use this to log request structure, chunk counts, TTFA/TTFT and durations, so the
voice pipeline can be debugged from the log files alone.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "data" / "logs"

FMT = "%(asctime)s | %(tag)-4s | %(levelname)-5s | %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"


class _TagFilter(logging.Filter):
    def __init__(self, tag: str) -> None:
        super().__init__()
        self.tag = tag

    def filter(self, record: logging.LogRecord) -> bool:
        record.tag = self.tag
        return True


def setup(name: str, tag: str, level: str = "INFO") -> logging.Logger:
    """Configure root logging for a service: file + stdout, tagged format."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter(FMT, datefmt=DATEFMT)
    flt = _TagFilter(tag)

    fh = RotatingFileHandler(LOG_DIR / f"{name}.log", maxBytes=8_000_000,
                             backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt); fh.addFilter(flt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt); sh.addFilter(flt)
    root.addHandler(fh); root.addHandler(sh)

    # quieten noisy third-party loggers so our lines stand out
    for noisy in ("httpx", "httpcore", "urllib3", "huggingface_hub", "filelock",
                  "asyncio", "uvicorn.access", "python_multipart", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logging.getLogger(name)


def preview(text: str, n: int = 90) -> str:
    """One-line, length-capped preview of a text payload for logs."""
    t = " ".join((text or "").split())
    return (t[:n] + "…") if len(t) > n else t
