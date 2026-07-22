# NOTES — per-section write-ups & trade-offs

This file collects the required half-page write-ups for each section of the
Electro-Pi technical test, plus the honest limitations of this build.

---

## Section 1 — LiveKit Agents (real-time voice)

**What's implemented.** `backend/realtime/agent.py` runs a real `AgentSession`
pipeline (STT → LLM → TTS) on a self-hosted LiveKit server (`bin/livekit-server
--dev`, no cloud keys). The `Agent` subclass carries the restaurant persona and
exposes two `@function_tool`s the LLM calls mid-conversation: `retrieve_kb(query)`
(the RAG tool) and `get_order_status(order_id)` (mocked lookup). STT wraps our
QwenCleo ASR service and TTS wraps our OmniVoice service, so the pipeline is fully
decoupled from any one vendor.

**Barge-in / interruption handling.** AgentSession is configured with
`allow_interruptions=True` and `min_interruption_duration=0.5s`. The flow: Silero
VAD continuously detects user speech even while the agent is talking; once speech
exceeds the min-duration threshold, the session cancels the in-flight TTS playback
and LLM generation, flushes the output, and re-opens the STT stream for the new
utterance. To make this robust I would additionally (a) debounce on the EoU
probability so a short "aha/uh-huh" backchannel doesn't cancel the turn (we already
gate on `min_interruption_duration` + `min_interruption_words`), and (b) keep a
"spoken-so-far" pointer so that after an interruption the agent knows which part of
its answer the user actually heard, and can resume/repeat intelligently rather than
restart.

**End-of-utterance (EoU).** Two signals are combined: VAD silence endpointing
(`min_silence_ms`) and a semantic turn-detector (`livekit-plugins-turn-detector`
`MultilingualModel`, Arabic-capable) that predicts whether the transcribed text is
a complete turn — so the agent waits when the user trails off on a connector
("...علشان") instead of interrupting them. A lightweight HTTP EoU service
(`services/eou_service.py`) serves the same semantic signal to the browser path.

**Adding a second tool safely.** `get_order_status` shows the pattern: a typed
signature (`order_id: str`) becomes the tool's JSON schema automatically, a
docstring documents intent for the LLM, and the body validates input and returns a
plain string. For safety in production I'd: validate/normalize the id before any
lookup; wrap the backend call in a timeout + try/except and return a *graceful*
natural-language error the LLM can relay ("معلش، مش قادر أجيب حالة الطلب دلوقتي")
rather than throwing; keep the tool idempotent and read-only where possible; and
add per-tool rate limiting so a mis-firing LLM can't hammer a downstream service.

**Bonus 1.2 — swapping a pipeline component.** The pipeline is vendor-decoupled by
design: `config.yaml → tts.engine` switches OmniVoice **VoiceTut ↔ Lahgtna**
(different checkpoints, same interface) with zero code change, and the LLM backend
switches **Gemini ↔ local vLLM** the same way. In the LiveKit worker, swapping STT
or TTS is a one-line change of the adapter class — e.g. `stt=deepgram.STT()` instead
of `QwenCleoSTT()` — because both conform to the `stt.STT` / `tts.TTS` base classes.

---

## Section 2 — RAG (LangChain / LangGraph)

**What's implemented.** `backend/rag/` chunks documents (paragraph-packing to
~800 chars with 120-char overlap), embeds them with `multilingual-e5-small`
(Arabic-capable), and stores them in FAISS (cosine via normalized inner-product).
Retrieval is **hybrid**: dense FAISS fused with BM25 sparse scores (0.65/0.35).
The agent is a **LangGraph** ReAct agent (`agent/graph.py`) whose LLM is bound to
a `retrieve_kb` tool; it decides when to retrieve, answers with citations back to
the source chunk (`(المصدر: menu.md ص3)`), and streams tokens.

**Hallucination guardrail.** The retrieval tool returns the sentinel
`NO_RELEVANT_CONTEXT` when the best hit is below `rag.score_threshold` (0.30). The
guardrail system prompt instructs the agent to *refuse* in that case and for any
out-of-domain question, instead of guessing. Verified: three in-KB questions answer
correctly with citations; an out-of-scope question ("English Premier League news")
is refused with no tool call and no invented facts. See `README.md` for the 3
example Q&A.

**Multimodal.** PDFs/DOCX are parsed for text *and* tables (pdfplumber → markdown
rows) and embedded images are captioned by Gemini vision at ingest; the caption is
embedded so images/tables become retrievable, and the rendered page screenshot is
shown in the chat and the Data-tab viewer.

**If answer quality on longer docs were poor**, in priority order I'd: (1) add a
**cross-encoder re-ranker** (e.g. bge-reranker) over the top-20 dense+sparse
candidates — the single biggest quality lever; (2) move to **structure-aware
chunking** (split on headings/sections, keep tables whole) and add small
parent-document / sentence-window retrieval so a matched sentence pulls in its
surrounding context; (3) tune hybrid weights and `top_k` per corpus, and add query
rewriting / HyDE for vague questions; (4) upgrade the embedder to `e5-base/large`
or `bge-m3`. The store already does hybrid; re-ranking is the natural next step.

---

## Section 3 — Quantization

**What's implemented.** `quantization/quantize_benchmark.py` loads
`Qwen2.5-3B-Instruct` twice — bf16 and 4-bit NF4 (bitsandbytes via transformers) —
and measures peak VRAM, time-to-first-token, and decode throughput on 5 fixed
prompts, writing a table + raw outputs to `quantization/results/`. See
`quantization/results/RESULTS.md` for the measured numbers on this box (RTX 4060 Ti
16 GB).

**When to pick which technique (from experience/reasoning).**
- **bitsandbytes 4-bit (NF4)** — best for *quick* memory savings with no calibration
  step: load-time quantization, great for fitting a model on a smaller GPU or for
  QLoRA fine-tuning. Downsides: slower kernels than a compiled quantized format, and
  inference throughput doesn't improve much (sometimes regresses) versus fp16.
- **GPTQ / AWQ** — pick these for *production inference latency*: they do offline,
  calibration-based 4-bit weight quantization that vLLM/TGI serve with fast fused
  kernels, so you get both the memory saving *and* higher throughput. AWQ tends to
  preserve quality slightly better on instruction models; GPTQ is more widely
  supported. Worth the one-time calibration cost when the model is served at scale.
- **GGUF (llama.cpp)** — pick this for *CPU / edge / Mac / mixed hardware* or when
  you want a single portable file with flexible k-quant levels (Q4_K_M, Q5_K_M…). It
  shines off-GPU and for laptop/on-device deployment; on a datacenter GPU, AWQ/GPTQ
  under vLLM will out-throughput it.

Rule of thumb I use: **bitsandbytes to prototype / fit, AWQ (or GPTQ) under vLLM to
serve on GPU, GGUF to ship to CPU/edge.**

---

## Section 4 — Model Deployment

**What's implemented.** `deployment/Dockerfile` serves `Qwen2.5-3B-Instruct` behind
an **OpenAI-compatible, streaming** API using **vLLM**. `deployment/loadtest.py`
fires N concurrent streaming requests and reports TTFT (p50/p95), total latency, and
aggregate throughput. Results on this box in `deployment/results.md`.

**Why vLLM over a hand-rolled FastAPI + transformers loop?** PagedAttention +
continuous batching give far higher throughput under concurrency (which is the whole
point of the 50-user question), token streaming (SSE) and an OpenAI-compatible schema
come for free (so the same client targets Gemini or this server unchanged), and it
ships prefix caching, health checks, and Prometheus metrics. A hand-rolled loop
processes requests largely serially and would fall over under load.

**Serving 50 concurrent users in production.** (1) **Batching** — vLLM's continuous
batching already coalesces concurrent decodes; raise `--max-num-seqs` and size
`--gpu-memory-utilization`/`--max-model-len` to the KV-cache budget. (2) **Quantize**
the weights (AWQ) to free VRAM for a bigger KV cache = more concurrent sequences per
GPU. (3) **Horizontal autoscaling** — run several replicas behind a load balancer,
autoscaled on queue depth / GPU utilization (K8s HPA + KEDA). (4) **A queue** in
front (so bursts don't drop requests) with admission control + per-user rate limits
and back-pressure. (5) **Caching** — prefix/prompt caching for shared system prompts,
and a semantic response cache for repeated FAQs. (6) **Observability + SLOs** on TTFT
and tokens/sec, with tensor-parallel or a larger GPU if a single card can't hold the
target concurrency at the latency SLO.

---

## Voice-pipeline latency (measured, RTX 4060 Ti)

The voice agent streams end-to-end: ASR emits partial transcripts while you speak,
the LLM streams tokens, and TTS audio plays chunk-by-chunk as it's synthesized.

| Stage | Measured |
|---|---|
| LLM time-to-first-token (Gemini, thinking off) | **0.8 – 1.1 s** |
| TTS time-to-first-audio (streaming, warm) | **1.4 – 1.7 s** |
| ASR streaming window (partials while speaking) | 1.5 s |

**The single biggest win was the TTS diffusion step count.** On one Arabic
sentence (~3 s of audio):

| `tts.num_step` | generation | RTF |
|---|---|---|
| 32 (original default) | 10.3 s | 3.40× — slower than realtime, unusable live |
| 16 | 2.9 s | 1.03× |
| **8 (new default)** | **1.6 s** | **0.50× — 2× faster than realtime** |
| 4 | 1.0 s | 0.33× (fastest, slightly rougher) |

Two other fixes mattered: `gemini-2.5-flash` is a *thinking* model, and its hidden
reasoning added multi-second stalls plus coarse chunking — disabling thinking
(`thinking_budget=0`) restored true token streaming; and uvicorn silently returns
**404 on WebSocket routes** when no websocket implementation is installed, which
is why the ASR/TTS envs must have `websockets` (see requirements notes).

Citations are stripped before synthesis (and suppressed entirely on the voice
channel) so the TTS never reads "(المصدر: menu.md)" out loud.

## Honest limitations of this build

- **Single 16 GB GPU.** A local 30B isn't feasible; the local LLM path uses
  Qwen2.5-3B. Gemini is the default LLM so ASR + TTS (+ EoU) fit alongside it;
  running local vLLM **and** ASR+TTS simultaneously is tight — documented in the
  README (use Gemini + voice, or vLLM alone).
- **No Docker in the dev box.** LiveKit runs from the native `livekit-server`
  binary (the script falls back to Docker if present). `deployment/Dockerfile` is
  provided and correct but was not `docker build`-verified on this machine; the vLLM
  server + load test were validated running natively instead.
- **HF rate-limiting** during the build meant the dense embedder is
  `multilingual-e5-small` (not `-base`); the store degrades gracefully to BM25-only
  if the embedder is ever unavailable, and auto-activates FAISS once it's cached.
- **UI screenshots** couldn't be captured in this headless WSL image (Chromium's
  system libs aren't installed and there's no sudo). The production build compiles
  cleanly and every backing API is verified; open `http://127.0.0.1:8080` to view.
- **Egyptian-dialect answers** depend on the LLM; Gemini tends toward MSA. The
  system prompts request Arabic; for strict Egyptian dialect the local Qwen path or
  a dialect-tuned model would be swapped in via `config.yaml`.
