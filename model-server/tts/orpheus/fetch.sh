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

# The one file the server cannot start without. Checked after download rather
# than trusted: a gated repo can return a directory of everything except the
# weights, and the CLI still exits 0.
WANT=model.safetensors

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
# Everything, including vocos/. The server decodes with SNAC's own decoder
# today and ignores those files, but the checkpoint was tuned to be decoded by
# the Vocos decoder shipped beside it, so porting that is the next step and
# re-downloading 6.6 GB to get two files would be silly. banner.png is the only
# thing skipped: it is 860 kB of nothing this needs.
set -- download "$REPO" --local-dir "$DEST/$SUB" --exclude "banner.png"
[ -n "${HF_TOKEN:-}" ] && set -- "$@" --token "$HF_TOKEN"
"$CLI" "$@"

if [ ! -f "$DEST/$SUB/$WANT" ]; then
  echo "ERROR: $WANT missing from $DEST/$SUB." >&2
  echo "The download reported success, so this is most likely the licence" >&2
  echo "accepted on the account but not granted to the token in use." >&2
  exit 1
fi

echo
echo "done. $(du -sh "$DEST/$SUB" | cut -f1) in $DEST/$SUB"
echo
echo "The slot reads it at /models/$SUB, which is this folder's models/ dir"
echo "bind-mounted read-only. If model-server/.env pins ORPHEUS_MODEL_PATH at an"
echo "older checkpoint, that override wins over the compose default -- change it"
echo "or drop the line."
