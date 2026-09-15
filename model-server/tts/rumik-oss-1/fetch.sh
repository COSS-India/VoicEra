#!/bin/sh
# Download the rumik-oss-1 checkpoint into this folder, where compose.extra.yml
# expects it.
#
# Run this BEFORE bringing the stack up. Docker creates a missing bind-mount
# source as an empty root-owned directory, so starting first leaves the
# container looking at nothing, and its error is about a model path rather than
# about the order things were done in.
#
# scripts/start-model-server.sh finds this file by existence and runs it with
# the TTS slot's token in HF_TOKEN. The repo is NOT gated -- unlike
# bodhan-ai/indic-speak next door -- so no credential is required and none is
# demanded here. A token is passed through when one happens to be set, because
# an authenticated request gets a higher rate limit.
#
# Could this be skipped entirely? Their server.py calls snapshot_download() at
# startup, so yes, technically: the model would appear on first boot. Three
# reasons it is done here instead. A 7.2 GB download inside a container start
# looks exactly like a hang for as long as it lasts; it would land in the
# hf_cache volume rather than somewhere an operator can see, measure or delete;
# and it would happen AFTER a 20-minute image build rather than before, so a
# licence or network problem surfaces at the latest possible moment.
#
# Licence: CC-BY-NC-4.0 with an acceptable-use addendum. Research and
# non-commercial use only; a commercial deployment needs separate permission
# from Rumik. See this folder's README.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
DEST=${RUMIK_MODELS_DIR:-"$HERE/models"}

REPO=${RUMIK_REPO:-rumik-ai/rumik-oss-1}
SUB=${RUMIK_MODEL_DIRNAME:-rumik-oss-1}

# The two files the server cannot start without: the first weight shard and the
# Mimi codec. Checked after the download rather than trusted -- the CLI exits 0
# on a partial fetch, and a missing codec surfaces minutes into a load as a
# path error rather than as a failed download.
WANT_MODEL=model-00001-of-00002.safetensors
WANT_CODEC=codec/model.safetensors

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
# assets/ is 4 MB of README images and samples/ is 7 MB of demo wavs. Neither is
# loaded by anything; benchmarks/ is kept because it is the only record of what
# the published scores were measured on.
set -- download "$REPO" --local-dir "$DEST/$SUB" \
       --exclude "assets/*" --exclude "samples/*"
[ -n "${HF_TOKEN:-}" ] && set -- "$@" --token "$HF_TOKEN"
"$CLI" "$@"

for want in "$WANT_MODEL" "$WANT_CODEC"; do
  if [ ! -f "$DEST/$SUB/$want" ]; then
    echo "ERROR: $want missing from $DEST/$SUB." >&2
    echo "The download reported success, so this is a partial fetch rather than" >&2
    echo "a permission problem -- the repo is public. Re-run; the CLI resumes." >&2
    exit 1
  fi
done

echo
echo "done. $(du -sh "$DEST/$SUB" | cut -f1) in $DEST/$SUB"
echo
echo "The slot reads it at /models/$SUB, which is this folder's models/ dir"
echo "bind-mounted read-only. If model-server/.env pins RUMIK_MODEL_PATH at a"
echo "different path, that override wins over the compose default -- change it"
echo "or drop the line."
