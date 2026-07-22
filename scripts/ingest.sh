#!/usr/bin/env bash
# Ingest documents into the vector store from the CLI.
#   scripts/ingest.sh <file-or-dir> [more...]      (default: data/kb)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$VA_ROOT"
CUDA_VISIBLE_DEVICES="$VA_GPU" "$(py "$ENV_APP")" -m backend.rag.ingest "${@:-data/kb}"
