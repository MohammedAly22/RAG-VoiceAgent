#!/usr/bin/env bash
# Deliberately download the dense embedding model into the HF cache (with retries
# + mirror fallback). Once cached, the vector store auto-activates FAISS dense
# retrieval on the next (re)index. Safe to run anytime.
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
MODEL="$(grep -E '^[[:space:]]*embedding_model:' "$VA_ROOT/config.yaml" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
echo "▶ preparing embedder: $MODEL"
for attempt in 1 2 3 4 5 6; do
  echo "  attempt $attempt …"
  VA_EMBED_ALLOW_DOWNLOAD=1 HF_HUB_ENABLE_HF_TRANSFER=0 \
    "$(py "$ENV_APP")" - "$MODEL" <<'PY' && { echo "  ✓ embedder ready"; exit 0; }
import sys
from sentence_transformers import SentenceTransformer
m = SentenceTransformer(sys.argv[1], device="cpu")
print("  dim:", m.get_sentence_embedding_dimension())
PY
  echo "  (failed; trying mirror in 5s)"; export HF_ENDPOINT=https://hf-mirror.com; sleep 5
done
echo "✗ could not download embedder — staying in BM25-only mode"; exit 1
