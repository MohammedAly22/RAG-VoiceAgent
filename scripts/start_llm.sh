#!/usr/bin/env bash
# Start the local LLM service (Qwen2.5-3B via vLLM, OpenAI-compatible, streaming).
# Only needed when config.yaml llm.backend == "vllm". Default backend is Gemini.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
LOG="$VA_LOGS/llm.out"
MODEL="$(cfg model_path)"; MODEL="${MODEL:-Qwen/Qwen2.5-3B-Instruct}"
QUANT_ARGS=""
if [ "${VA_LLM_4BIT:-0}" = "1" ]; then QUANT_ARGS="--quantization bitsandbytes"; fi
echo "▶ LLM (vLLM) | model=$MODEL | GPU=$VA_GPU | port=$LLM_PORT"
echo "  log: $LOG"
CUDA_VISIBLE_DEVICES="$VA_GPU" PYTHONUNBUFFERED=1 \
  "$(py "$ENV_LLM")" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" --served-model-name voiceagent-llm \
    --host 127.0.0.1 --port "$LLM_PORT" \
    --gpu-memory-utilization 0.55 --max-model-len 8192 --dtype auto \
    --enable-prefix-caching $QUANT_ARGS \
  2>&1 | log_prefix | tee -a "$LOG"
