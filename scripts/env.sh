#!/usr/bin/env bash
# Shared environment for all Voice Agent service scripts.
# Edit GPU / ports / conda envs here once; config.yaml stays the source of truth
# for model choices.

# --- paths ---
export VA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export VA_BACKEND="$VA_ROOT/backend"
export VA_LOGS="$VA_ROOT/data/logs"
mkdir -p "$VA_LOGS"

# --- GPU ---
export VA_GPU="${VA_GPU:-0}"

# --- conda env names (create them per the README; override via env vars if needed) ---
export ENV_APP="${ENV_APP:-voiceagent}"   # FastAPI app + LangGraph + RAG + LiveKit worker
export ENV_ASR="${ENV_ASR:-test-qwen}"    # qwencleo-asr
export ENV_TTS="${ENV_TTS:-omnivoice}"    # voicetut-tts
export ENV_LLM="${ENV_LLM:-test-qwen}"    # vLLM (local LLM path)
export ENV_NODE="${ENV_NODE:-node-env}"   # dedicated conda env with Node 20 for the React build
                                          # create it with:  conda create -n node-env nodejs=20 -y

# --- conda base (portable: ask conda, else common per-user install locations) ---
CONDA_BASE="$(conda info --base 2>/dev/null || true)"
if [ -z "$CONDA_BASE" ]; then
  for d in "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/miniforge3" "$HOME/mambaforge" /opt/conda; do
    [ -d "$d" ] && { CONDA_BASE="$d"; break; }
  done
fi
: "${CONDA_BASE:=$HOME/miniconda3}"       # last-resort default (no hardcoded username)
py()   { echo "$CONDA_BASE/envs/$1/bin/python"; }
# Node bin dir: use the dedicated `node-env` conda env (see README step 3). If it
# isn't created yet, fall back to any `node` on PATH (nvm/system) so it still works.
node_bin() {
  local d="$CONDA_BASE/envs/$ENV_NODE/bin"
  if [ -x "$d/node" ]; then echo "$d"
  elif command -v node >/dev/null 2>&1; then dirname "$(command -v node)"
  else echo "$d"; fi   # fall back (build_ui.sh prints a helpful error if node is missing)
}
export -f py node_bin
export CONDA_BASE

# --- read a scalar from config.yaml (simple grep; good enough for ports/ids) ---
cfg() {  # cfg <regex-key>  → value after first match
  grep -E "^[[:space:]]*$1:" "$VA_ROOT/config.yaml" 2>/dev/null | head -1 \
    | sed -E "s/.*$1:[[:space:]]*\"?([^\"#]+)\"?.*/\1/" | sed -E 's/[[:space:]]+$//'
}
export -f cfg

# --- service ports (must match config.yaml) ---
export APP_PORT=8080
export ASR_PORT=8021
export TTS_PORT=8022
export EOU_PORT=8023
export LLM_PORT=8011
export LIVEKIT_PORT=7880

export TMUX_SESSION="voiceagent"

log_prefix() { while IFS= read -r line; do echo "[$(date '+%H:%M:%S')] $line"; done; }
export -f log_prefix
