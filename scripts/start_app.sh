#!/usr/bin/env bash
# Start the FastAPI app (UI + REST + WebSocket chat + config/data/logs APIs).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
LOG="$VA_LOGS/app.out"
echo "▶ APP (FastAPI) | port=$APP_PORT"
echo "  log: $LOG"
cd "$VA_ROOT"
CUDA_VISIBLE_DEVICES="$VA_GPU" PYTHONUNBUFFERED=1 \
  "$(py "$ENV_APP")" -m uvicorn backend.app:app --host 0.0.0.0 --port "$APP_PORT" \
  2>&1 | log_prefix | tee -a "$LOG"
