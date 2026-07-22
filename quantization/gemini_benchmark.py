"""Benchmark Gemini on the REAL grounded restaurant prompts (Section 3 companion).

Runs the same `restaurant_prompts.json` fixture that the local bf16/4-bit benchmark
uses, so the three backends are compared on identical inputs. Measures TTFT and
total latency via true token streaming (the same path the app uses) and captures
each answer for the quality comparison.

    conda activate voiceagent            # has google-genai + .env with GEMINI_API_KEY
    python quantization/gemini_benchmark.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# load .env (GEMINI_API_KEY)
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from config import CFG  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(exist_ok=True)
PROMPTS = json.loads((Path(__file__).resolve().parent / "restaurant_prompts.json").read_text("utf-8"))["prompts"]


def bench() -> dict:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    model = CFG.llm.gemini.model
    cfg = types.GenerateContentConfig(
        temperature=CFG.llm.temperature, max_output_tokens=CFG.llm.max_tokens,
        thinking_config=types.ThinkingConfig(thinking_budget=0))
    outs, ttfts, totals = [], [], []
    for p in PROMPTS:
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=p["user"])])]
        c = types.GenerateContentConfig(system_instruction=p["system"], **{
            k: getattr(cfg, k) for k in ("temperature", "max_output_tokens", "thinking_config")})
        t0 = time.time(); first = None; parts = []
        stream = client.models.generate_content_stream(model=model, contents=contents, config=c)
        for chunk in stream:
            if chunk.text:
                if first is None:
                    first = time.time() - t0
                parts.append(chunk.text)
        total = time.time() - t0
        answer = "".join(parts).strip()
        outs.append({"question": p["question"], "output": answer})
        ttfts.append(first or total); totals.append(total)
        print(f"  {p['question']:28s} TTFT={first:.2f}s total={total:.2f}s")
    return {
        "backend": f"gemini:{model}",
        "avg_ttft_s": round(sum(ttfts) / len(ttfts), 3),
        "avg_total_s": round(sum(totals) / len(totals), 3),
        "peak_vram_gb": 0.0,          # cloud — no local VRAM
        "outputs": outs,
    }


if __name__ == "__main__":
    print(f"=== Gemini benchmark ({CFG.llm.gemini.model}) on {len(PROMPTS)} restaurant prompts ===")
    r = bench()
    (RESULTS / "gemini.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), "utf-8")
    print(f"\navg TTFT={r['avg_ttft_s']}s  avg total={r['avg_total_s']}s  →  {RESULTS/'gemini.json'}")
