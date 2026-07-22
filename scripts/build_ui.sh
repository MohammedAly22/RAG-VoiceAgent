#!/usr/bin/env bash
# Build the React UI into frontend-react/dist (served by FastAPI).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$VA_ROOT/frontend-react"
export PATH="$(node_bin):$PATH"

# Node must be available (Node 18+) — normally from the dedicated `node-env` conda
# env. Give a clear, actionable message instead of a cryptic "vite: not found".
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "✗ Node.js / npm not found (looked in the '$ENV_NODE' conda env and on PATH)."
  echo "  Create the dedicated Node env once, then retry:"
  echo "      conda create -n $ENV_NODE nodejs=20 -y"
  echo "  (or install Node 18+ via nvm / your system package manager)."
  exit 1
fi
echo "  using node $(node -v) · npm $(npm -v)  (env: $ENV_NODE or PATH)"

# Install deps if the vite binary is missing (a bare or prod-only node_modules
# won't have it — vite is a devDependency, so force dev deps regardless of NODE_ENV).
if [ ! -x node_modules/.bin/vite ]; then
  echo "  installing UI dependencies (incl. dev)…"
  npm install --include=dev --no-audit --no-fund
fi

npm run build
echo "✓ UI built → frontend-react/dist"
