#!/usr/bin/env bash
# Start the ASR service (QwenCleo-ASR — Egyptian + code-switching). Reused from Sano.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
LOG="$VA_LOGS/asr.out"
echo "▶ ASR (QwenCleo) | GPU=$VA_GPU | port=$ASR_PORT"
echo "  log: $LOG"
cd "$VA_BACKEND"
CUDA_VISIBLE_DEVICES="$VA_GPU" PYTHONUNBUFFERED=1 \
  "$(py "$ENV_ASR")" services/asr_service.py \
  2>&1 | log_prefix | tee -a "$LOG"
