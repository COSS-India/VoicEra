#!/bin/sh
# Pre-download Higgs TTS 3 into the stack's hf_cache volume.
#
# scripts/start-model-server.sh finds this file by existence and runs it before
# the build. The repo is PUBLIC, NOT GATED: no token is required and none is
# demanded. One is passed through when set, for the higher rate limit.
#
# Why bother, when the sidecar would download on first start anyway: ~10 GB
# arriving inside a container start looks exactly like a hang for as long as it
# lasts, and it would happen AFTER the image build rather than before, so a
# network problem surfaces at the latest possible moment. Here it surfaces
# first, with a progress bar.
#
# It downloads INTO THE VOLUME the sidecar reads (voicera-model-server_hf_cache,
# at /root/.cache/huggingface), using a throwaway python container, so the
# files are where the sidecar looks and nothing lands on the host's own disk.
#
# The reference clips are NOT fetched here: they come from a gated dataset and
# are committed once rather than downloaded per deployment. See
# voices/README.md and scripts/fetch_voices.py.
#
# Licence: Boson Higgs TTS 3 Research and Non-Commercial License. See README.md.
set -eu

# Resolved from this file's location, not the current directory, so the run is
# the same wherever setup was started from.
HERE=$(cd "$(dirname "$0")" && pwd)
ENV_FILE="$HERE/../../.env"

# The two keys this reads may be set in model-server/.env rather than exported,
# so read them from there when the environment does not have them -- the same
# well-formed-lines-only reading as compose-files.sh, never sourcing the file.
from_env_file() {
  [ -f "$ENV_FILE" ] || return 0
  grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"'\r'
}
HIGGS_MODEL_ID=${HIGGS_MODEL_ID:-$(from_env_file HIGGS_MODEL_ID)}
USE_SHARED_HF_CACHE=${USE_SHARED_HF_CACHE:-$(from_env_file USE_SHARED_HF_CACHE)}

REPO=${HIGGS_MODEL_ID:-bosonai/higgs-tts-3-4b}
VOLUME=${HIGGS_HF_CACHE_VOLUME:-voicera-model-server_hf_cache}
# Only the files a checkpoint load needs; skips anything else the repo carries.
WANT=config.json

# With USE_SHARED_HF_CACHE the stack reads another stack's cache instead
# (compose.shared-hf-cache.yml), which belongs to that stack and is not ours to
# write. Say so and leave it: the operator decides whether it should hold Higgs.
if [ -n "${USE_SHARED_HF_CACHE:-}" ]; then
  echo "fetch.sh: USE_SHARED_HF_CACHE is set; not writing $REPO into another stack's cache." >&2
  echo "          The sidecar will download it on first start if it is not already there." >&2
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "fetch.sh: docker not found; the sidecar will download $REPO on first start instead." >&2
  exit 0
fi

echo "Fetching $REPO into volume $VOLUME (public repo; ~10 GB on first run) ..."
docker volume create "$VOLUME" >/dev/null
docker run --rm \
  -e HF_TOKEN="${HF_TOKEN:-}" \
  -e REPO="$REPO" -e WANT="$WANT" \
  -v "$VOLUME":/root/.cache/huggingface \
  python:3.12-slim sh -c '
    pip install -q "huggingface_hub>=0.34" &&
    python - <<PY
import os
from huggingface_hub import snapshot_download
path = snapshot_download(os.environ["REPO"], token=os.environ.get("HF_TOKEN") or None)
want = os.path.join(path, os.environ["WANT"])
weights = [f for f in os.listdir(path) if f.endswith(".safetensors")]
# Checked rather than trusted: a partial fetch exits 0 and surfaces minutes
# into a load as a missing-file error.
assert os.path.isfile(want), f"{want} missing after download"
assert weights, f"no .safetensors in {path} after download"
print(f"ok: {path} ({len(weights)} weight file(s))")
PY'
