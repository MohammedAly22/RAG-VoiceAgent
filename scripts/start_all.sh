#!/usr/bin/env bash
# Start the full stack in a tmux session. Voice/LiveKit services are optional
# (they need the GPU); the app + Gemini LLM + RAG work without them.
#   scripts/start_all.sh            → app only (chat + RAG, Gemini)
#   scripts/start_all.sh voice      → app + ASR + TTS + EoU
#   scripts/start_all.sh full       → app + voice + LiveKit
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
MODE="${1:-app}"
tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true
tmux new-session -d -s "$TMUX_SESSION" -n app "bash $VA_ROOT/scripts/start_app.sh; bash"
if [ "$MODE" = "voice" ] || [ "$MODE" = "full" ]; then
  # Only load the local QwenCleo ASR (GPU/VRAM) when it's the selected provider.
  # With asr.provider=gemini, transcription runs inside the app — no ASR service.
  ASR_PROVIDER="$(grep -A6 '^asr:' "$VA_ROOT/config.yaml" | grep -m1 'provider:' | awk '{print $2}' | tr -d '\"'"'"' ')"
  if [ "${ASR_PROVIDER:-qwencleo}" = "qwencleo" ]; then
    tmux new-window  -t "$TMUX_SESSION" -n asr "bash $VA_ROOT/scripts/start_asr.sh; bash"
  else
    echo "  ASR: provider=$ASR_PROVIDER → skipping QwenCleo service (Gemini is app-native)."
  fi
  tmux new-window  -t "$TMUX_SESSION" -n tts "bash $VA_ROOT/scripts/start_tts.sh; bash"
  tmux new-window  -t "$TMUX_SESSION" -n eou "bash $VA_ROOT/scripts/start_eou.sh; bash"
fi
if [ "$MODE" = "full" ]; then
  bash "$VA_ROOT/scripts/start_livekit.sh" || true
  tmux new-window  -t "$TMUX_SESSION" -n lkagent "bash $VA_ROOT/scripts/start_livekit_agent.sh; bash"
fi
echo "Started tmux session '$TMUX_SESSION' (mode=$MODE)."
echo "  attach: tmux attach -t $TMUX_SESSION      status: scripts/status.sh"
echo "  UI:     http://127.0.0.1:$APP_PORT"
