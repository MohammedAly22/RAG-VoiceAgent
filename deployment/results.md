# Section 4 — Deployment: load / latency results

**Model:** Qwen/Qwen2.5-3B-Instruct  ·  **GPU:** RTX 4060 Ti 16 GB (WSL2)
**Server used for these numbers:** `deployment/serve.py` (FastAPI + transformers,
OpenAI-compatible, SSE streaming). The production path is the vLLM `Dockerfile`
(see note below). Streaming (token-by-token SSE) verified on `/v1/chat/completions`.

## Measurements (`deployment/loadtest.py`)

| Scenario | Reqs OK | Wall | TTFT mean / p95 | Total mean / p95 | Throughput |
|---|---|---|---|---|---|
| **Baseline** (concurrency 1, 128 tok) | 1/1 | 23.0 s | 2.13 / 2.13 s | 23.0 / 23.0 s | 2.4 tok/s |
| **Load** (concurrency 10, 48 tok) | 10/10 | 205.6 s | 162.6 / 195.8 s | 169.9 / 205.6 s | 1.0 tok/s |

## Reading the result

A single request has a healthy **2.1 s time-to-first-token**. Under **10 concurrent**
requests, TTFT p95 explodes to **~196 s** — because this transformers-based server
**serializes** generation (one `model.generate` at a time; concurrent requests
queue). All 10 requests still succeed, but the tail latency is unusable under load.

**This is precisely the motivation for vLLM** (the containerized production path in
`deployment/Dockerfile`): PagedAttention + **continuous batching** would run those
10 sequences *together* in one batch, keeping per-request TTFT low and multiplying
aggregate throughput, instead of queuing them. See the Section-4 write-up in
[`../NOTES.md`](../NOTES.md) for the full 50-user scaling plan (batching, quantized
weights for a bigger KV cache, replica autoscaling, a request queue, and caching).

## Note on vLLM on this box

`deployment/Dockerfile` (vLLM, OpenAI-compatible, streaming) is the intended
production server and it **loads the model successfully** (weights in 8 s). On this
particular **WSL2** dev box, vLLM's KV-cache memory profiler misreports available
VRAM (`No available memory for the cache blocks`), a known WSL quirk — so the load
numbers above were taken from the portable `serve.py` fallback instead. On a native
Linux GPU host the vLLM image serves directly:

```bash
docker build -t voiceagent-llm -f deployment/Dockerfile .
docker run --gpus all -p 8011:8011 voiceagent-llm
python deployment/loadtest.py --url http://localhost:8011/v1 --concurrency 10
```
