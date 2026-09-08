#!/bin/sh
# Download both checkpoints into this folder, where compose.extra.yml expects them.
#
# Run this BEFORE bringing the stack up. Docker creates a missing bind-mount source as an
# empty root-owned directory, so starting first leaves the container looking at
# nothing, and its error is about a model path rather than about the order things
# were done in. That has already happened once on this box.
#
# Both repos are GATED. Request access on each model page while logged in to
# HuggingFace, or the download 401s with nothing to say it was a permission
# problem:
#   https://huggingface.co/ai4bharat/indic-asr-nemotron-600m
#   https://huggingface.co/ai4bharat/bhili-asr-nemotron-600m
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
DEST=${NEMOTRON_MODELS_DIR:-"$HERE/models"}

INDIC_REPO=${NEMOTRON_INDIC_REPO:-ai4bharat/indic-asr-nemotron-600m}
BHILI_REPO=${NEMOTRON_BHILI_REPO:-ai4bharat/bhili-asr-nemotron-600m}

# The exact files the server looks for. Checked after download rather than
# trusted: a gated repo can return a directory of everything except the weights.
INDIC_FILE=indic_nemotron_v1_1_sft_600k_lr1-averaged-40k.nemo
BHILI_FILE=indic_nemotron_bhili_sft_lr1-averaged.nemo

if [ -z "${HF_TOKEN:-}" ] && [ ! -f "$HOME/.cache/huggingface/token" ]; then
  echo "ERROR: no HuggingFace credentials." >&2
  echo "Both checkpoints are gated. Run 'huggingface-cli login', or export HF_TOKEN." >&2
  exit 1
fi

if ! command -v hf >/dev/null 2>&1 && ! command -v huggingface-cli >/dev/null 2>&1; then
  echo "installing huggingface_hub[cli]" >&2
  # --break-system-packages: Ubuntu 23.04+ marks the system Python externally
  # managed (PEP 668) and pip refuses without it.
  pip3 install --quiet --break-system-packages "huggingface_hub[cli]"
fi
CLI=hf
command -v hf >/dev/null 2>&1 || CLI=huggingface-cli

mkdir -p "$DEST"

get() {
  repo=$1; sub=$2; want=$3
  echo
  echo "--- $repo -> $DEST/$sub"
  set -- download "$repo" --local-dir "$DEST/$sub"
  [ -n "${HF_TOKEN:-}" ] && set -- "$@" --token "$HF_TOKEN"
  "$CLI" "$@"
  if [ ! -f "$DEST/$sub/$want" ]; then
    echo "ERROR: $want missing from $DEST/$sub." >&2
    echo "The download reported success, so this is most likely gated access" >&2
    echo "granted to the account but not to the token in use." >&2
    exit 1
  fi
}

get "$INDIC_REPO" indic-asr-nemotron-600m "$INDIC_FILE"
get "$BHILI_REPO" bhili-asr-nemotron-600m "$BHILI_FILE"

echo
echo "done. $(du -sh "$DEST" | cut -f1) in $DEST"
echo
echo "Next:"
echo "  echo 'STT_MODEL=indic-nemotron' >> model-server/.env"
echo "  docker compose \$(sh model-server/compose-files.sh) \\"
echo "    --project-directory model-server up -d --build"
echo
echo "(no service name: this model's overlay also configures the gateway, and"
echo " 'up -d --build stt' would leave the gateway pointed at the wrong port)"
