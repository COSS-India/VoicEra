#!/bin/sh
# Download the Orpheus Indic checkpoint into this folder, where compose.extra.yml
# expects it.
#
# Run this BEFORE bringing the stack up. Docker creates a missing bind-mount
# source as an empty root-owned directory, so starting first leaves the
# container looking at nothing, and its error is about a model path rather than
# about the order things were done in.
#
# This folder had no fetch.sh until now, and the README claimed vLLM would pull
# the weights from HuggingFace on first start. It would not: ORPHEUS_MODEL_PATH
# defaults to a directory inside the read-only bind mount, and vLLM only
# auto-downloads when it is given a repo id. The weights actually came from a
# Google Drive folder of raw training output, by hand, five files at a time --
# see UPSTREAM-README.md. bodhan-ai/indic-speak is that model published, so
# there is finally something to fetch.
#
# The repo is GATED. Accept the licence on the model page while logged in to
# HuggingFace, or the download 401s with nothing to say it was a permission
# problem:
#   https://huggingface.co/bodhan-ai/indic-speak
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
DEST=${ORPHEUS_MODELS_DIR:-"$HERE/models"}

REPO=${ORPHEUS_REPO:-bodhan-ai/indic-speak}
SUB=${ORPHEUS_MODEL_DIRNAME:-indic-speak}

# The files the server cannot start without. Checked after download rather than
# trusted: a gated repo can return a directory of everything except the weights,
# and the CLI still exits 0.
#
# vocos/best.pt is on this list because the slot decodes with it. Leave it out
# and a partial download still passes here, then fails minutes later at
# container start with a model-path error instead of the licence hint below.
WANT="model.safetensors vocos/best.pt"

if [ -z "${HF_TOKEN:-}" ] && [ ! -f "$HOME/.cache/huggingface/token" ]; then
  echo "ERROR: no HuggingFace credentials." >&2
  echo "bodhan-ai/indic-speak is gated. Run 'huggingface-cli login', or export" >&2
  echo "HF_TOKEN (or TTS_HF_TOKEN, which the setup script passes to this slot)." >&2
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

echo
echo "--- $REPO -> $DEST/$SUB"
# Everything, including vocos/ -- that directory holds the decoder the slot
# actually runs, plus the loader that builds it from the checkpoint's own
# config. banner.png is the only thing skipped: 860 kB of nothing this needs.
set -- download "$REPO" --local-dir "$DEST/$SUB" --exclude "banner.png"
[ -n "${HF_TOKEN:-}" ] && set -- "$@" --token "$HF_TOKEN"
"$CLI" "$@"

for want in $WANT; do
  if [ ! -f "$DEST/$SUB/$want" ]; then
    echo "ERROR: $want missing from $DEST/$SUB." >&2
    echo "The download reported success, so this is most likely the licence" >&2
    echo "accepted on the account but not granted to the token in use." >&2
    exit 1
  fi
done

echo
echo "done. $(du -sh "$DEST/$SUB" | cut -f1) in $DEST/$SUB"
echo
echo "The slot reads it at /models/$SUB, which is this folder's models/ dir"
echo "bind-mounted read-only. If model-server/.env pins ORPHEUS_MODEL_PATH at an"
echo "older checkpoint, that override wins over the compose default -- change it"
echo "or drop the line."
