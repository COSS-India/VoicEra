#!/bin/sh
# Download FearL0rd/Chatterbox-TTS-Portuguese into ./checkpoints/portuguese,
# where server.py looks.
#
# Run this BEFORE bringing the stack up: Docker creates a missing bind-mount
# source as an empty root-owned directory.
#
# The repo is public (MIT, not gated), so no token is needed. ~3.2 GB.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
DEST=${PTC_CHECKPOINTS_DIR:-"$HERE/checkpoints"}
REPO=${PTC_REPO:-FearL0rd/Chatterbox-TTS-Portuguese}

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

# The exact files ChatterboxTTS.from_local() opens. conds.pt is the voice.
for f in ve.safetensors t3_cfg.safetensors s3gen.safetensors tokenizer.json conds.pt; do
  if [ ! -f "$DEST/portuguese/$f" ]; then
    echo "ERROR: $f missing from $DEST/portuguese" >&2
    exit 1
  fi
done
echo "ok: $(du -sh "$DEST/portuguese" | cut -f1) in $DEST/portuguese"
