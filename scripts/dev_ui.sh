#!/usr/bin/env bash
# Run the Vite dev server (hot reload) proxying /api to the FastAPI app.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$VA_ROOT/frontend-react"
export PATH="$(node_bin):$PATH"
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "✗ Node.js / npm not found. Create the dedicated Node env once:"
  echo "      conda create -n $ENV_NODE nodejs=20 -y"
  exit 1
fi
# Install deps if vite is missing (bare or prod-only node_modules won't have it).
[ -x node_modules/.bin/vite ] || npm install --include=dev --no-audit --no-fund
npm run dev -- --host
