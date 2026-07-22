# 🛠️ Backend — services, APIs & internals

The backend is a **FastAPI orchestrator** (`app.py`) plus a set of **small model services**, each in
its own process (and conda env) so heavy models can be started/stopped and scheduled on the GPU
independently. The orchestrator serves the built UI, exposes the REST + WebSocket API, runs the RAG
agent, and proxies streaming audio to/from the model services.

```
Browser ──REST/WS──▶ app.py :8080 (env: voiceagent)
                        ├─ agent/  RAG agent  (route → retrieve → generate, streaming)
                        ├─ rag/    ingest + FAISS + hybrid retrieval (multimodal)
                        ├─ db.py   SQLite: sessions · messages · calls
                        ├──HTTP/WS─▶ ASR service  :8021  (env: test-qwen)   [optional]
                        ├──HTTP/WS─▶ TTS service  :8022  (env: omnivoice)   [optional]
                        ├──HTTP────▶ EoU service  :8023  (env: voiceagent)  [optional]
                        ├──HTTP────▶ vLLM LLM     :8011  (env: test-qwen)   [optional]
                        └──HTTPS───▶ Gemini API                              (default LLM/ASR)
```

---

## 📡 Services

| Service | File | Port / env | Purpose | Optional? |
|---|---|---|---|---|
| **App / orchestrator** | `app.py` | `:8080` · `voiceagent` | UI + REST + WS chat/asr/tts proxies + config/data/logs/sessions/calls APIs; runs the RAG agent. | **required** |
| **ASR** (speech→text) | `services/asr_service.py` | `:8021` · `test-qwen` | QwenCleo streaming Egyptian-Arabic ASR over `ws /ws/stream`. Silence-gated, degenerate-repeat filtered. | optional — only if `asr.provider: qwencleo` |
| **TTS** (text→speech) | `services/tts_service.py` (+ `lahgtna_tts.py`) | `:8022` · `omnivoice` | OmniVoice / VoiceTut / Lahgtna synthesis; `ws /ws/stream` for chunked, low-latency audio. Citations & filenames stripped, Arabic digits → ASCII. | optional — needed for any spoken output |
| **EoU** (turn detection) | `services/eou_service.py` | `:8023` · `voiceagent` | End-of-utterance probability for a finalized transcript → `data/logs/eou.log`. | optional |
| **LLM (local)** | `deployment/serve.py` **or** vLLM Docker | `:8011` · `test-qwen` | OpenAI-compatible streaming server for Qwen2.5-3B when `llm.backend: vllm`. | optional — Gemini is default |
| **Gemini** | `asr_gemini.py`, `agent/llm.py` | cloud | Default **LLM**, app-native **ASR** (one-shot), and **vision captioning** at ingest. | default |

Health of all services: `scripts/status.sh` or `GET /api/config` (`services` field). The app reports
`asr: true` automatically when `asr.provider: gemini` (transcription is app-native — no service needed).

---

## 🌐 Key API endpoints (`app.py`)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/config` | Effective config + live service health. |
| `POST` | `/api/config` | Hot-swap config (in-place — importers see it immediately). |
| `WS` | `/api/chat` | Streaming chat: `tool_call → retrieved → token* → done`. Persists the turn to SQLite. |
| `WS` | `/api/asr/stream` | Mic PCM → live partials / final transcript (QwenCleo streaming **or** Gemini; `oneshot` control for chat voice). |
| `WS` | `/api/tts/stream` | Text → chunked PCM (low time-to-first-audio). |
| `POST` | `/api/asr` · `/api/tts` | One-shot transcribe / synthesize. |
| `GET/POST/DELETE` | `/api/sessions`, `/api/calls`, `/api/data`, `/api/logs` | Dashboard + data + logs. |
| `POST` | `/api/persona/suggest` | LLM-generated system prompt for the "Other" category. |

---

## 🧠 Core modules

- **`config.py`** — loads `config.yaml` + `.env` into a dot-accessible `CFG`. `save()` mutates `CFG`
  **in place** so `from config import CFG` importers pick up hot-swaps without a restart.
- **`db.py`** — SQLite: `sessions`, `messages` (with docs/tools/refused), `calls` (transcript + audio + summary).
- **`asr_gemini.py`** — Gemini ASR provider: one-shot `atranscribe`, rolling `GeminiStreamSession`,
  `system_instruction` (so the prompt is never echoed), energy/duration gating, repeat-collapse.
- **`logging_setup.py`** — rotating per-service `.log` files under `data/logs/` with aligned tags.
- **`agent/`** — the RAG agent → see [`agent/README.md`](agent/README.md).
- **`rag/`** — `ingest.py` (loaders, chunking, vision fallback for mangled Arabic PDF text layers),
  `store.py` (FAISS + BM25 hybrid), `multimodal.py` (page-image render + captions).
- **`realtime/agent.py`** — the LiveKit `AgentSession` worker (Section 1): persona `Agent`,
  `@function_tool` `retrieve_kb` + mock `get_order_status`, barge-in, EoU.

---

## ⚡ Latency & streaming design

- **Chat:** true token streaming over WS; the client "drips" tokens for a smooth typewriter effect.
- **Voice out:** the answer is spoken **sentence-by-sentence** — TTS starts on the first sentence
  instead of waiting for the full answer (big perceived-latency win). A speaking-latch holds the
  barge-in gate across the streamed turn.
- **Voice in:** VAD-gated mic (silence never reaches the recognizer). Gemini finals reuse the last
  partial when it already covers the buffer, skipping a redundant transcription.
- **EoU** runs **off** the critical path (fire-and-forget logging), so it never delays ASR→LLM.
- **TTS knob:** `tts.num_step` (diffusion steps) is the dominant latency/quality trade-off
  (see `NOTES.md`: 32→RTF 3.4 unusable, 8→RTF 0.5).

---

## ⚠️ Limitations & gotchas

- **`websockets` must be installed in the ASR (`test-qwen`) and TTS (`omnivoice`) envs** — uvicorn
  **silently 404s** WebSocket routes without a WS implementation, which breaks streaming ASR/TTS.
- **Single 16 GB GPU:** QwenCleo ASR + OmniVoice TTS + a local LLM together is tight. Comfortable
  combos: *Gemini LLM + ASR/TTS services*, or *local vLLM alone*. Prefer `asr.provider: gemini` to
  free ~2–3 GB when you don't need local ASR.
- **vLLM on WSL2** mis-reads KV-cache VRAM → use `deployment/serve.py` locally; the vLLM Docker image
  is the production path on native Linux.
- Services are **stateless** except the app's SQLite; deleting `data/voiceagent.sqlite` resets history.
