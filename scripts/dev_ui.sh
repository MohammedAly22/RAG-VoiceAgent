#!/usr/bin/env bash
# Run the Vite dev server (hot reload) proxying /api to the FastAPI app.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$VA_ROOT/frontend-react"
export PATH="$(node_bin):$PATH"
[ -d node_modules ] || npm install
npm run dev -- --host
