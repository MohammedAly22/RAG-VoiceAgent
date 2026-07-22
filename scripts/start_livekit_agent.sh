#!/usr/bin/env bash
# Run the livekit-agents worker (STT->LLM->TTS, barge-in, EoU, tools).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
set -a; [ -f "$VA_ROOT/.env" ] && source "$VA_ROOT/.env"; set +a
LOG="$VA_LOGS/livekit_agent.out"
echo "▶ LiveKit agent worker"
echo "  log: $LOG"
cd "$VA_BACKEND"
CUDA_VISIBLE_DEVICES="$VA_GPU" PYTHONUNBUFFERED=1 \
  "$(py "$ENV_APP")" realtime/agent.py dev \
  2>&1 | log_prefix | tee -a "$LOG"
