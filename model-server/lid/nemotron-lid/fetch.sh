#!/bin/sh
# Ensure the Nemotron .nemo checkpoint used by the LID probe is under models/.
#
# compose.extra.yml bind-mounts models/ read-only at /models. Prefer a local
# hardlink/copy of the same file indic-nemotron STT already holds (identical
# SHA) before downloading ~2.4 GB from HuggingFace.
set -eu

HERE=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
DEST=${LID_MODELS_DIR:-"$HERE/models"}
mkdir -p "$DEST"

NEMO_NAME=indic_nemotron_v1_1_sft_600k_lr1-averaged-40k.nemo
TARGET="$DEST/$NEMO_NAME"

# Same weights as STT indic-nemotron — reuse when present (hardlink if same FS).
reuse_candidates="
$HERE/../../stt/indic-nemotron/models/indic-asr-nemotron-600m/$NEMO_NAME
${NEMOTRON_MODELS_DIR:-}/indic-asr-nemotron-600m/$NEMO_NAME
"

if [ ! -f "$TARGET" ]; then
  for src in $reuse_candidates; do
    [ -n "$src" ] || continue
    [ -f "$src" ] || continue
    if ln "$src" "$TARGET" 2>/dev/null; then
      echo "[ok] hardlinked $src -> $TARGET"
      break
    fi
    if cp -f "$src" "$TARGET"; then
      echo "[ok] copied $src -> $TARGET"
      break
    fi
  done
fi

export NEMOTRON_MODEL_CACHE_DIR="$DEST"
export NEMOTRON_MODEL_REPO_ID="${NEMOTRON_MODEL_REPO_ID:-vedantahatti/nemotron-lid}"

if [ -z "${HF_TOKEN:-}${LID_HF_TOKEN:-}" ] && [ ! -f "${HOME}/.cache/huggingface/token" ]; then
  echo "NOTE: no HF_TOKEN / cached login. If the repo is gated, export HF_TOKEN=hf_..."
fi

# Prefer LID_HF_TOKEN, then HF_TOKEN (same pattern as other slots).
if [ -n "${LID_HF_TOKEN:-}" ]; then
  export HF_TOKEN="$LID_HF_TOKEN"
fi

cd "$HERE"
python3 - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, str(Path(".").resolve()))
from nemotron_lid import resolve_nemo_checkpoint, NEMO_FILENAME, EXPECTED_NEMO_SHA256, sha256_file

path = resolve_nemo_checkpoint(force_download=False, verify_hash=True)
digest = sha256_file(path)
print(f"[ok] checkpoint: {path}")
print(f"[ok] filename  : {NEMO_FILENAME}")
print(f"[ok] sha256    : {digest}")
assert digest == EXPECTED_NEMO_SHA256
PY

echo
echo "Weights ready under $DEST (mounted read-only at /models)."
echo "Next: set LID_MODEL=nemotron-lid and include lid in COMPOSE_PROFILES."
