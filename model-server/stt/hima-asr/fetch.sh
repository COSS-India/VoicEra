#!/bin/sh
# Download Hima-ASR into models/ beside this file. The slot bind-mounts this whole
# folder at /app, so the server finds it at /app/models/hima-asr with no extra volume.
#
# scripts/start-model-server.sh runs this before the build. Driving Compose by
# hand, run it first: without the checkpoint the server refuses to start and
# says so.
#
# PINNED TO A COMMIT, on purpose. The model loads with trust_remote_code, so the
# repo's modeling_hima_asr.py runs inside our container. Pinning means the code
# that runs is the code someone reviewed; bumping HIMA_REVISION is a review, not
# a refresh. The image also sets HF_HUB_OFFLINE so it can never fetch on its own.
#
# Public repo, not gated: no token needed. The decide/ folder (the 17.5M decision
# head and its demo clips) is skipped -- the STT slot does not serve it.
#
# Idempotent: a complete download at the pinned revision is left alone.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
DEST="$HERE/models/hima-asr"
REPO=${HIMA_REPO:-Prahaladha/hima-asr}
# 2026-11-04, "README: simpler speed table" -- 0.46B, trimmed 63,335-piece table.
REVISION=${HIMA_REVISION:-7f7fd3034a7fed7fdd1c752e3d83251ce0a7dd7b}

# Files the server cannot start without. Checked after download rather than
# trusted: a partial download exits 0 just as happily.
REQUIRED="model.safetensors config.json configuration_hima_asr.py modeling_hima_asr.py preprocessor_config.json tokenizer.json tokenizer_config.json"

complete() {
  [ -f "$DEST/.revision" ] && [ "$(cat "$DEST/.revision")" = "$REVISION" ] || return 1
  for f in $REQUIRED; do [ -f "$DEST/$f" ] || return 1; done
}

if complete; then
  echo "  hima-asr already present at $REVISION"
  exit 0
fi

mkdir -p "$DEST"
echo "  Downloading $REPO@$REVISION (~1 GB)"

# Use the host's HuggingFace CLI if it already has one. If not, run the download
# in a throwaway container rather than pip-installing into the host's Python:
# this script runs on shared GPU boxes, and installing into their system
# packages is a change to something that is not ours. The container writes as
# the calling user, so the files are not root-owned.
if command -v hf >/dev/null 2>&1 || command -v huggingface-cli >/dev/null 2>&1; then
  CLI=hf
  command -v hf >/dev/null 2>&1 || CLI=huggingface-cli
  set -- download "$REPO" --revision "$REVISION" --local-dir "$DEST" --exclude "decide/*"
  [ -n "${HF_TOKEN:-}" ] && set -- "$@" --token "$HF_TOKEN"
  "$CLI" "$@"
elif command -v docker >/dev/null 2>&1; then
  DOCKER=docker
  docker ps >/dev/null 2>&1 || DOCKER="sudo docker"
  echo "  (no hf CLI on this host; downloading in a throwaway python:3.12-slim container)"
  $DOCKER run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e HF_TOKEN="${HF_TOKEN:-}" \
    -v "$DEST:/out" python:3.12-slim sh -c "
      pip install --quiet --no-cache-dir --target /tmp/hf 'huggingface_hub>=0.34' &&
      PYTHONPATH=/tmp/hf python -m huggingface_hub.cli.hf download '$REPO' \
        --revision '$REVISION' --local-dir /out --exclude 'decide/*'"
else
  echo "ERROR: need either the HuggingFace CLI ('hf') or docker to download." >&2
  echo "This script does not pip-install into the host's Python." >&2
  exit 1
fi

for f in $REQUIRED; do
  if [ ! -f "$DEST/$f" ]; then
    echo "ERROR: $f missing from $DEST after download." >&2
    exit 1
  fi
done
echo "$REVISION" > "$DEST/.revision"

echo
echo "done. $(du -sh "$DEST" | cut -f1) in $DEST"
echo "Next:"
echo "  echo 'STT_MODEL=hima-asr' >> model-server/.env"
echo "  docker compose \$(sh model-server/compose-files.sh) --project-directory model-server up -d --build stt"
