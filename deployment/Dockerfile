# =============================================================================
# Section 4 — Model deployment.  Serves Qwen2.5-3B-Instruct behind an
# OpenAI-compatible, streaming HTTP API using vLLM.
#
# Why vLLM (over a hand-rolled FastAPI + transformers loop)?
#   • PagedAttention + continuous batching → far higher throughput under load,
#     which is exactly what Section 4's "50 concurrent users" write-up is about.
#   • Token streaming (SSE) and an OpenAI-compatible schema out of the box, so
#     the same client code targets Gemini or this local server unchanged.
#   • Production features for free: prefix caching, metrics, health endpoints.
#
# Build & run:
#   docker build -t voiceagent-llm -f deployment/Dockerfile .
#   docker run --gpus all -p 8011:8011 \
#       -e MODEL=Qwen/Qwen2.5-3B-Instruct voiceagent-llm
#   # then:  python deployment/loadtest.py --url http://localhost:8011/v1
# =============================================================================
FROM vllm/vllm-openai:latest

ENV MODEL=Qwen/Qwen2.5-3B-Instruct \
    SERVED_NAME=voiceagent-llm \
    MAX_LEN=8192 \
    GPU_MEM_UTIL=0.85 \
    PORT=8011

EXPOSE 8011

# vLLM's image entrypoint is the OpenAI server; pass our args via a shell so the
# env vars above are substituted at runtime.
ENTRYPOINT []
CMD ["/bin/sh", "-c", "python3 -m vllm.entrypoints.openai.api_server \
    --model ${MODEL} --served-model-name ${SERVED_NAME} \
    --host 0.0.0.0 --port ${PORT} \
    --max-model-len ${MAX_LEN} --gpu-memory-utilization ${GPU_MEM_UTIL} \
    --enable-prefix-caching --dtype auto"]
