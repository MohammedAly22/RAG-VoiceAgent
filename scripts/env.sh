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

# --- conda envs (verified present on this box) ---
export ENV_APP="voiceagent"     # FastAPI app + LangGraph + RAG + LiveKit worker
export ENV_ASR="test-qwen"      # qwencleo-asr
export ENV_TTS="omnivoice"      # voicetut-tts
export ENV_LLM="test-qwen"      # vLLM (local LLM path)
export ENV_NODE="sano-node"     # node 20 for the React build

# --- conda python launchers ---
CONDA_BASE="$(conda info --base 2>/dev/null || echo /home/ahmed/miniconda3)"
py()   { echo "$CONDA_BASE/envs/$1/bin/python"; }
node_bin() { echo "$CONDA_BASE/envs/$ENV_NODE/bin"; }
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
