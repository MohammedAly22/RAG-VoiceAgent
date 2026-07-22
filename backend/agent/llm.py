"""Plug-and-play LLM interface with true token streaming.

`astream_tokens()` yields real tokens as they are produced:
  - gemini → native google-genai async streaming, with **thinking disabled**
    (gemini-2.5-flash is a thinking model; disabling it removes the multi-second
    stall and gives smooth, low-latency token streaming).
  - vllm   → OpenAI-compatible async streaming against the local server.

`get_chat_model()` / `complete()` remain for one-shot uses (persona suggestion).
Switching backend is a one-line config change (config.yaml / Settings tab).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import AsyncIterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CFG  # noqa: E402

log = logging.getLogger("agent.llm")


# ---------------------------------------------------------------------------
# streaming (used by the RAG agent + voice)
# ---------------------------------------------------------------------------
async def astream_tokens(system: str, history: list[dict], user: str) -> AsyncIterator[str]:
    backend = CFG.llm.backend
    if backend == "gemini":
        async for t in _gemini_stream(system, history, user):
            yield t
    elif backend == "vllm":
        async for t in _vllm_stream(system, history, user):
            yield t
    else:
        raise ValueError(f"unknown llm.backend: {backend!r}")


async def _gemini_stream(system: str, history: list[dict], user: str) -> AsyncIterator[str]:
    from google import genai
    from google.genai import types
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    client = genai.Client(api_key=key)
    contents = []
    for m in history:
        role = "user" if m.get("role") == "user" else "model"
        contents.append(types.Content(role=role,
                        parts=[types.Part.from_text(text=m.get("content", ""))]))
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user)]))
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=CFG.llm.temperature,
        max_output_tokens=CFG.llm.max_tokens,
        thinking_config=types.ThinkingConfig(thinking_budget=0),  # low latency
    )
    stream = await client.aio.models.generate_content_stream(
        model=CFG.llm.gemini.model, contents=contents, config=cfg)
    async for chunk in stream:
        if chunk.text:
            yield chunk.text


async def _vllm_stream(system: str, history: list[dict], user: str) -> AsyncIterator[str]:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(base_url=CFG.llm.vllm.base_url, api_key="EMPTY")
    messages = [{"role": "system", "content": system}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": user})
    stream = await client.chat.completions.create(
        model=CFG.llm.vllm.served_model_name, messages=messages, stream=True,
        temperature=CFG.llm.temperature, max_tokens=CFG.llm.max_tokens)
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


# ---------------------------------------------------------------------------
# one-shot (persona suggestion, summaries)
# ---------------------------------------------------------------------------
def get_chat_model(*, streaming: bool = False, temperature: float | None = None):
    backend = CFG.llm.backend
    temp = CFG.llm.temperature if temperature is None else temperature
    if backend == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY not set")
        return ChatGoogleGenerativeAI(model=CFG.llm.gemini.model, google_api_key=key,
                                      temperature=temp, max_output_tokens=CFG.llm.max_tokens)
    if backend == "vllm":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=CFG.llm.vllm.served_model_name, base_url=CFG.llm.vllm.base_url,
                          api_key="EMPTY", temperature=temp, max_tokens=CFG.llm.max_tokens)
    raise ValueError(f"unknown llm.backend: {backend!r}")


def complete(prompt: str, *, temperature: float = 0.5) -> str:
    resp = get_chat_model(temperature=temperature).invoke(prompt)
    return (resp.content if hasattr(resp, "content") else str(resp)).strip()
