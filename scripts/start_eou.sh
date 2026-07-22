#!/usr/bin/env bash
# Start the EoU (end-of-utterance / turn-detection) service.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
LOG="$VA_LOGS/eou.out"
echo "▶ EoU (turn detection) | port=$EOU_PORT"
echo "  log: $LOG"
cd "$VA_BACKEND"
PYTHONUNBUFFERED=1 "$(py "$ENV_APP")" services/eou_service.py \
  2>&1 | log_prefix | tee -a "$LOG"
