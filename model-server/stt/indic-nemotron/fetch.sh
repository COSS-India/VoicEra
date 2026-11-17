#!/bin/sh
# Download both checkpoints into this folder, where compose.extra.yml expects them.
#
# Run this BEFORE bringing the stack up. Docker creates a missing bind-mount source as an
# empty root-owned directory, so starting first leaves the container looking at
# nothing, and its error is about a model path rather than about the order things
# were done in. That has already happened once on this box.
#
# Two checkpoints, from two places:
#
#   multilingual  HuggingFace, GATED. Request access on the model page while
#                 logged in, or the download 401s with nothing to say it was a
#                 permission problem:
#                   https://huggingface.co/ai4bharat/indic-asr-nemotron-600m
#
#   Bhili         AI4Bharat's 2026-10-05 retrain, shared on Google Drive. It has
#                 the SAME filename as the release on HuggingFace, so it gets its
#                 own dated folder: two checkpoints that cannot be told apart by
#                 name must at least be told apart by path, or nothing on disk or
#                 in the logs says which one is serving.
#                 The previous release is still reachable for rollback with
#                 NEMOTRON_BHILI_SOURCE=hf (also gated):
#                   https://huggingface.co/ai4bharat/bhili-asr-nemotron-600m
#
# Idempotent: a checkpoint already in place is verified, not downloaded again.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
DEST=${NEMOTRON_MODELS_DIR:-"$HERE/models"}

INDIC_REPO=${NEMOTRON_INDIC_REPO:-ai4bharat/indic-asr-nemotron-600m}
BHILI_REPO=${NEMOTRON_BHILI_REPO:-ai4bharat/bhili-asr-nemotron-600m}

# The exact files the server looks for. Checked after download rather than
# trusted: a gated repo can return a directory of everything except the weights.
INDIC_FILE=indic_nemotron_v1_1_sft_600k_lr1-averaged-40k.nemo
BHILI_FILE=indic_nemotron_bhili_sft_lr1-averaged.nemo

# ---- Bhili: which checkpoint ------------------------------------------------
#   drive  AI4Bharat's 2026-10-05 retrain (default; what compose.extra.yml loads)
#   hf     the original HuggingFace release (rollback)
BHILI_SOURCE=${NEMOTRON_BHILI_SOURCE:-drive}
BHILI_DRIVE_ID=${NEMOTRON_BHILI_DRIVE_ID:-1ZVfylGZTlRYAX_W0WQh2Smv-sO7Clwt6}
BHILI_DRIVE_DIR=bhili-asr-nemotron-600m-2026-10-05
BHILI_HF_DIR=bhili-asr-nemotron-600m

# sha256 of the Drive checkpoint. AI4Bharat published none, so this is pinned
# from the first download (see the message printed below when it is empty).
# Once pinned, a truncated download or a Drive "quota exceeded" HTML page saved
# under the checkpoint's name fails HERE, instead of as a load error -- or worse,
# as no error at all: the engine skips a Bhili file it cannot find and quietly
# serves Bhili from the multilingual model.
BHILI_SHA256=${NEMOTRON_BHILI_SHA256:-}

case "$BHILI_SOURCE" in
  drive|hf) ;;
  *) echo "ERROR: NEMOTRON_BHILI_SOURCE must be 'drive' or 'hf', not '$BHILI_SOURCE'" >&2
     exit 1 ;;
esac

if [ -z "${HF_TOKEN:-}" ] && [ ! -f "$HOME/.cache/huggingface/token" ]; then
  echo "ERROR: no HuggingFace credentials." >&2
  echo "The multilingual checkpoint is gated. Run 'huggingface-cli login', or export HF_TOKEN." >&2
  exit 1
fi

pip_get() {
  echo "installing $1" >&2
  # --break-system-packages: Ubuntu 23.04+ marks the system Python externally
  # managed (PEP 668) and pip refuses without it.
  pip3 install --quiet --break-system-packages "$1"
}

if ! command -v hf >/dev/null 2>&1 && ! command -v huggingface-cli >/dev/null 2>&1; then
  pip_get "huggingface_hub[cli]"
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

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

# A .nemo is a tar archive with model_config.yaml inside. Checking that catches
# the failure Drive is known for: an HTML interstitial (virus-scan warning, quota
# exceeded) written to disk under the name you asked for, with exit status 0.
looks_like_nemo() {
  tar -tf "$1" 2>/dev/null | grep -q 'model_config\.yaml$'
}

get_drive() {
  id=$1; sub=$2; want=$3
  out="$DEST/$sub/$want"
  echo
  echo "--- drive:$id -> $out"
  mkdir -p "$DEST/$sub"
  if [ -f "$out" ]; then
    echo "already present; verifying rather than downloading again"
  else
    command -v gdown >/dev/null 2>&1 || pip_get "gdown>=5"
    # To a .part first: an interrupted download must never sit at the path the
    # engine loads from.
    gdown "$id" -O "$out.part"
    mv "$out.part" "$out"
  fi
  if ! looks_like_nemo "$out"; then
    echo "ERROR: $out is not a .nemo archive (no model_config.yaml inside)." >&2
    echo "Drive most likely served an HTML page instead -- quota exceeded, or the" >&2
    echo "file is no longer shared by link. Delete it and retry, or download it in" >&2
    echo "a browser and copy it to exactly this path; this script will verify it." >&2
    exit 1
  fi
  got=$(sha256_of "$out")
  if [ -z "$BHILI_SHA256" ]; then
    echo
    echo "NOTE: no sha256 pinned for this checkpoint. This download's is:"
    echo "  $got"
    echo "Pin it as BHILI_SHA256's default in fetch.sh, so the next download is checked."
  elif [ "$got" != "$BHILI_SHA256" ]; then
    echo "ERROR: sha256 mismatch for $out" >&2
    echo "  expected $BHILI_SHA256" >&2
    echo "  got      $got" >&2
    echo "Truncated download, or a different file behind the same Drive link." >&2
    exit 1
  else
    echo "sha256 ok ($got)"
  fi
}

get "$INDIC_REPO" indic-asr-nemotron-600m "$INDIC_FILE"
if [ "$BHILI_SOURCE" = drive ]; then
  get_drive "$BHILI_DRIVE_ID" "$BHILI_DRIVE_DIR" "$BHILI_FILE"
  BHILI_DIR=$BHILI_DRIVE_DIR
else
  get "$BHILI_REPO" "$BHILI_HF_DIR" "$BHILI_FILE"
  BHILI_DIR=$BHILI_HF_DIR
fi

echo
echo "done. $(du -sh "$DEST" | cut -f1) in $DEST"
echo
if [ "$BHILI_SOURCE" = hf ]; then
  echo "Bhili is the HuggingFace release. compose.extra.yml loads the Drive one by"
  echo "default, so point it here explicitly in model-server/.env:"
  echo "  NEMOTRON_BHILI_NEMO_PATH=/models/$BHILI_HF_DIR/$BHILI_FILE"
  echo
fi
echo "Next:"
echo "  echo 'STT_MODEL=indic-nemotron' >> model-server/.env"
echo "  docker compose \$(sh model-server/compose-files.sh) \\"
echo "    --project-directory model-server up -d --build"
echo
echo "(no service name: this model's overlay also configures the gateway, and"
echo " 'up -d --build stt' would leave the gateway pointed at the wrong port)"
echo
echo "Then confirm WHICH Bhili checkpoint loaded -- /health only says that one did:"
echo "  docker logs voicera_model_stt 2>&1 | grep 'Loading bhili'"
echo "  # expect: .../$BHILI_DIR/$BHILI_FILE"
