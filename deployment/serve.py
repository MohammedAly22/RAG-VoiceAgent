"""Section 4 — a minimal OpenAI-compatible **streaming** FastAPI server for
Qwen2.5-3B (transformers backend).

Provided as a portable fallback to the vLLM deployment (`Dockerfile`): it needs
only transformers + torch, so it runs anywhere a GPU is visible (it also ran
reliably on this WSL dev box where vLLM's KV-cache profiler misreports memory).
For real production concurrency use the vLLM image — see the Section-4 write-up in
NOTES.md for why (continuous batching / PagedAttention).

Endpoints (subset of the OpenAI schema, so the same client + loadtest work):
  GET  /v1/models
  POST /v1/chat/completions   (supports "stream": true → SSE token streaming)

Run:
  conda activate test-qwen
  python deployment/serve.py --model Qwen/Qwen2.5-3B-Instruct --port 8011
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import uuid

import torch
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Voice Agent LLM (transformers)")
_STATE: dict = {}
# transformers can't safely run concurrent generate() on one model, so we
# serialize. Concurrent requests queue — the load test then measures realistic
# latency-under-load for a non-batching server (this is exactly what motivates
# vLLM's continuous batching; see NOTES.md Section 4).
_GEN_LOCK = threading.Lock()


class ChatReq(BaseModel):
    model: str | None = None
    messages: list[dict]
    max_tokens: int = 256
    temperature: float = 0.3
    stream: bool = False


def _load(model_id: str):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(
        model_id, torch_dtype=torch.bfloat16, device_map="cuda").eval()
    _STATE.update(tok=tok, model=model, model_id=model_id)


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": _STATE.get("served_name", "voiceagent-llm"),
            "object": "model", "owned_by": "local"}]}


def _prep(req: ChatReq):
    tok = _STATE["tok"]
    inputs = tok.apply_chat_template(req.messages, add_generation_prompt=True,
                                     return_tensors="pt").to("cuda")
    return tok, inputs


@app.post("/v1/chat/completions")
def chat(req: ChatReq):
    tok, inputs = _prep(req)
    model = _STATE["model"]
    cid = "chatcmpl-" + uuid.uuid4().hex[:12]
    created = int(_STATE["clock"]())

    if not req.stream:
        with _GEN_LOCK, torch.inference_mode():
            out = model.generate(inputs, max_new_tokens=req.max_tokens,
                                 do_sample=req.temperature > 0, temperature=max(req.temperature, 1e-5),
                                 pad_token_id=tok.eos_token_id)
        text = tok.decode(out[0, inputs.shape[1]:], skip_special_tokens=True)
        return {"id": cid, "object": "chat.completion", "created": created,
                "model": _STATE.get("served_name"), "choices": [{"index": 0,
                "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}

    from transformers import TextIteratorStreamer
    streamer = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True)
    kwargs = dict(inputs=inputs, max_new_tokens=req.max_tokens, streamer=streamer,
                  do_sample=req.temperature > 0, temperature=max(req.temperature, 1e-5),
                  pad_token_id=tok.eos_token_id)

    def _run():
        with _GEN_LOCK, torch.inference_mode():
            model.generate(**kwargs)
    threading.Thread(target=_run, daemon=True).start()

    def sse():
        for piece in streamer:
            chunk = {"id": cid, "object": "chat.completion.chunk", "created": created,
                     "model": _STATE.get("served_name"),
                     "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        done = {"id": cid, "object": "chat.completion.chunk", "created": created,
                "model": _STATE.get("served_name"),
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        yield f"data: {json.dumps(done)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-3B-Instruct")
    ap.add_argument("--served-name", default="voiceagent-llm")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8011)
    args = ap.parse_args()
    _STATE["served_name"] = args.served_name
    _STATE["clock"] = time.time
    print(f"loading {args.model} …")
    _load(args.model)
    print("ready.")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
