#!/usr/bin/env bash
# Quick health check of all Voice Agent services + GPU.
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
check() {  # name url
  if "$(py "$ENV_APP")" - "$2" <<'PY' 2>/dev/null
import sys, urllib.request
urllib.request.urlopen(sys.argv[1], timeout=3).read()
PY
  then echo "  ✓ $1  ($2)"; else echo "  ✗ $1  ($2)  DOWN"; fi
}
echo "Voice Agent services:"
check "APP" "http://127.0.0.1:$APP_PORT/api/health"
check "ASR" "http://127.0.0.1:$ASR_PORT/health"
check "TTS" "http://127.0.0.1:$TTS_PORT/health"
check "EoU" "http://127.0.0.1:$EOU_PORT/health"
check "LLM" "http://127.0.0.1:$LLM_PORT/v1/models"
echo
echo "LiveKit server (docker):"
docker ps --filter name=voiceagent-livekit --format '  {{.Names}} {{.Status}} {{.Ports}}' 2>/dev/null || echo "  (docker not available)"
echo
echo "GPU $VA_GPU:"
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader -i "$VA_GPU" 2>/dev/null | sed 's/^/  /'
