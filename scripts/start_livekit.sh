#!/usr/bin/env bash
# Start a local self-hosted LiveKit server with dev keys from .env.
# Prefers the native livekit-server binary (bin/livekit-server) — no Docker needed.
# Falls back to Docker if the binary is absent but Docker is present.
# Install the binary manually with: curl -sSL https://get.livekit.io | bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
set -a; [ -f "$VA_ROOT/.env" ] && source "$VA_ROOT/.env"; set +a
LK_KEY="${LIVEKIT_API_KEY:-devkey}"
LK_SECRET="${LIVEKIT_API_SECRET:-secret_dev_please_change_0123456789abcdef}"

BIN="$VA_ROOT/bin/livekit-server"
if [ ! -x "$BIN" ] && command -v livekit-server >/dev/null 2>&1; then
  BIN="$(command -v livekit-server)"
fi

if [ -x "$BIN" ]; then
  echo "▶ LiveKit server (native) | ws://127.0.0.1:$LIVEKIT_PORT | key=$LK_KEY"
  exec env LIVEKIT_KEYS="$LK_KEY: $LK_SECRET" "$BIN" --dev --bind 0.0.0.0
elif command -v docker >/dev/null 2>&1; then
  echo "▶ LiveKit server (docker) | ws://127.0.0.1:$LIVEKIT_PORT | key=$LK_KEY"
  docker rm -f voiceagent-livekit >/dev/null 2>&1 || true
  exec docker run --rm --name voiceagent-livekit \
    -p 7880:7880 -p 7881:7881 -p 7882:7882/udp \
    -e "LIVEKIT_KEYS=$LK_KEY: $LK_SECRET" \
    livekit/livekit-server --dev --bind 0.0.0.0
else
  echo "✗ livekit-server not found and Docker not available."
  echo "  Install the binary: curl -sSL https://get.livekit.io | bash"
  exit 1
fi
