#!/bin/sh
# Download BuzzASR/portuguese into ./models/portuguese, where server.py looks.
#
# Run this BEFORE bringing the stack up: Docker creates a missing bind-mount
# source as an empty root-owned directory, and the error is then about a model
# path rather than about the order things were done in.
#
# The repo is public (MIT, not gated), so no token is needed. ~3.1 GB.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
DEST=${PTW_MODELS_DIR:-"$HERE/models"}
REPO=${PTW_REPO:-BuzzASR/portuguese}

if ! command -v hf >/dev/null 2>&1 && ! command -v huggingface-cli >/dev/null 2>&1; then
  echo "installing huggingface_hub[cli]" >&2
  pip3 install --quiet --break-system-packages "huggingface_hub[cli]"
fi
CLI=hf
command -v hf >/dev/null 2>&1 || CLI=huggingface-cli

mkdir -p "$DEST/portuguese"
echo "--- $REPO -> $DEST/portuguese"
set -- download "$REPO" --local-dir "$DEST/portuguese"
[ -n "${HF_TOKEN:-}" ] && set -- "$@" --token "$HF_TOKEN"
"$CLI" "$@"

for f in model.safetensors config.json preprocessor_config.json tokenizer.json generation_config.json; do
  if [ ! -f "$DEST/portuguese/$f" ]; then
    echo "ERROR: $f missing from $DEST/portuguese" >&2
    exit 1
  fi
done
echo "ok: $(du -sh "$DEST/portuguese" | cut -f1) in $DEST/portuguese"
