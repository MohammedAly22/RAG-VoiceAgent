#!/usr/bin/env bash
# Start the TTS service (OmniVoice — VoiceTut/Lahgtna, engine-switchable). Reused from Sano.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
LOG="$VA_LOGS/tts.out"
echo "▶ TTS (OmniVoice) | GPU=$VA_GPU | port=$TTS_PORT"
echo "  log: $LOG"
cd "$VA_BACKEND"
CUDA_VISIBLE_DEVICES="$VA_GPU" PYTHONUNBUFFERED=1 \
  "$(py "$ENV_TTS")" services/tts_service.py \
  2>&1 | log_prefix | tee -a "$LOG"
