"""Section 4 — load / latency test for the streaming LLM endpoint.

Fires N concurrent chat-completion requests (streaming) at an OpenAI-compatible
server (vLLM local, or any /v1 endpoint) and reports:
  • time-to-first-token (TTFT) per request  — the streaming latency that matters
  • total latency per request
  • aggregate throughput (tokens/sec across all requests)

Usage:
  python deployment/loadtest.py --url http://127.0.0.1:8011/v1 \
      --model voiceagent-llm --concurrency 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import aiohttp

# Real restaurant workload (the same kind of grounded turn the app serves), so the
# load numbers reflect THIS product under concurrent customers, not a generic prompt.
SYSTEM = ("أنت مساعد مطعم مصري. جاوب على أسئلة العملاء بالعامية باختصار واعتمد على "
          "المعلومات المتاحة فقط.")
PROMPT = "مواعيد عمل المطعم إيه وأسعار المشويات كام؟"


async def one_request(session, url, model, idx, max_tokens=128) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens, "temperature": 0.3, "stream": True,
    }
    t0 = time.time()
    ttft = None
    n_tokens = 0
    async with session.post(f"{url}/chat/completions", json=payload) as resp:
        async for raw in resp.content:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0]["delta"].get("content")
            except Exception:  # noqa: BLE001
                delta = None
            if delta:
                if ttft is None:
                    ttft = time.time() - t0
                n_tokens += 1
    total = time.time() - t0
    return {"idx": idx, "ttft": ttft or total, "total": total, "tokens": n_tokens}


async def run(url, model, concurrency, max_tokens=128, timeout=300) -> None:
    print(f"→ {concurrency} concurrent streaming requests to {url} (model={model}, max_tokens={max_tokens})")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
        t0 = time.time()
        results = await asyncio.gather(*[
            one_request(s, url, model, i, max_tokens) for i in range(concurrency)],
            return_exceptions=True)
        wall = time.time() - t0

    ok = [r for r in results if isinstance(r, dict)]
    errs = [r for r in results if not isinstance(r, dict)]
    if not ok:
        print("all requests failed:", errs[:1]); return
    ttfts = [r["ttft"] for r in ok]
    totals = [r["total"] for r in ok]
    toks = sum(r["tokens"] for r in ok)

    def pctl(xs, p): return sorted(xs)[min(len(xs) - 1, int(len(xs) * p))]
    print(f"\nrequests ok: {len(ok)}/{concurrency}  (errors: {len(errs)})")
    print(f"wall time      : {wall:.2f}s")
    print(f"TTFT  mean/p50/p95 : {statistics.mean(ttfts):.3f} / {pctl(ttfts,.5):.3f} / {pctl(ttfts,.95):.3f} s")
    print(f"total mean/p50/p95 : {statistics.mean(totals):.3f} / {pctl(totals,.5):.3f} / {pctl(totals,.95):.3f} s")
    print(f"aggregate throughput: {toks/wall:.1f} tok/s ({toks} tokens total)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8011/v1")
    ap.add_argument("--model", default="voiceagent-llm")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--max-tokens", type=int, default=128)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()
    asyncio.run(run(args.url, args.model, args.concurrency, args.max_tokens, args.timeout))
