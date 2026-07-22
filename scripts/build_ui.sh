#!/usr/bin/env bash
# Build the React UI into frontend-react/dist (served by FastAPI).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$VA_ROOT/frontend-react"
export PATH="$(node_bin):$PATH"
[ -d node_modules ] || npm install
npm run build
echo "✓ UI built → frontend-react/dist"
