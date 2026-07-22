#!/usr/bin/env bash
# Stop everything.
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
tmux kill-session -t "$TMUX_SESSION" 2>/dev/null && echo "killed tmux '$TMUX_SESSION'" || echo "no tmux session"
docker rm -f voiceagent-livekit >/dev/null 2>&1 && echo "stopped LiveKit container" || true
for p in "$APP_PORT" "$ASR_PORT" "$TTS_PORT" "$EOU_PORT" "$LLM_PORT"; do
  pids=$(lsof -ti tcp:"$p" 2>/dev/null || true)
  [ -n "$pids" ] && kill $pids 2>/dev/null && echo "killed :$p" || true
done
echo "done"
