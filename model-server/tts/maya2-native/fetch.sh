#!/bin/sh
# Download everything maya2-native loads into this folder's models/, where
# compose.extra.yml mounts it read-only at /models:
#
#   models/maya2-native/   the release: weights, maya3_config.json, backbone/
#                          (Qwen3 config + tokenizer), voices/voices.json  ~5 GB
#   models/mimi/           kyutai/mimi, the audio codec                    ~0.4 GB
#   models/ecapa/          speechbrain/spkrec-ecapa-voxceleb               ~0.1 GB
#
# Run this BEFORE bringing the stack up. Docker creates a missing bind-mount
# source as an empty root-owned directory, so starting first leaves the server
# looking at nothing -- it then says so, naming this script, but the empty
# directory has to be removed by hand.
#
# scripts/start-model-server.sh finds this file by existence and runs it with
# the TTS slot's token in HF_TOKEN. None of the three repos is gated; a token is
# passed through when set only because authenticated requests get a higher rate
# limit.
#
# Upstream's from_pretrained() would download all of this on first boot. It is
# done here instead for the reason tts/rumik-oss-1/fetch.sh gives: a 5 GB
# download inside a container start looks exactly like a hang, and a network
# problem should surface before a long image build, not after.
#
# The ECAPA speaker encoder is only used for voice cloning, which is off
# (MAYA_VOICE_CLONING=false). It is fetched anyway because upstream's loader
# requires it to be present -- 80 MB is cheaper than patching that.
#
# Licences: weights Apache-2.0; Mimi CC-BY-4.0; ECAPA Apache-2.0. Keep their
# notices when redistributing. See this folder's README.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
DEST=${MAYA_MODELS_DIR:-"$HERE/models"}
case "$DEST" in /*) ;; *) DEST="$HERE/../../$DEST" ;; esac   # .env paths are relative to model-server/

REPO=${MAYA_REPO:-maya-research/maya2-native}
# Pin this to a commit SHA once a fetched release has been verified on hardware.
REVISION=${MAYA_REVISION:-main}

PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then
  echo "ERROR: python3 is needed to run the download." >&2
  exit 1
fi
if ! "$PY" -c "import huggingface_hub" >/dev/null 2>&1; then
  echo "installing huggingface_hub" >&2
  # --break-system-packages: Ubuntu 23.04+ marks the system Python externally
  # managed (PEP 668) and pip refuses without it.
  "$PY" -m pip install --quiet --user --break-system-packages huggingface_hub 2>/dev/null \
    || "$PY" -m pip install --quiet --user huggingface_hub
fi

mkdir -p "$DEST"

# The allow-lists are upstream's own (maya3/hub.py RELEASE_PATTERNS,
# MIMI_PATTERNS, ECAPA_PATTERNS), so nothing is fetched that the loader does not
# read. The codec and speaker-encoder repo ids are read from the release's
# maya3_config.json rather than assumed, which is what upstream's resolver does.
DEST="$DEST" REPO="$REPO" REVISION="$REVISION" "$PY" - <<'PYEOF'
import json
import os
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

dest = Path(os.environ["DEST"])
token = os.environ.get("HF_TOKEN") or None


def fetch(repo, sub, patterns, want, revision=None):
    target = dest / sub
    print(f"\n--- {repo}{'@' + revision if revision else ''} -> {target}", flush=True)
    snapshot_download(repo, revision=revision, local_dir=str(target), allow_patterns=patterns, token=token)
    # Checked rather than trusted: a partial fetch otherwise surfaces minutes
    # into a model load as a path error.
    missing = [f for f in want if not (target / f).is_file()]
    if missing:
        sys.exit(f"ERROR: {repo} is missing {missing} after download. Re-run; it resumes.")
    return target


release = fetch(os.environ["REPO"], "maya2-native",
                ["*.safetensors", "*.safetensors.index.json", "maya3_config.json", "config.json",
                 "backbone/*", "voices/*", "README.md", "LICENSE*", "NOTICE*"],
                ["maya3_config.json", "backbone/config.json", "backbone/tokenizer.json", "voices/voices.json"],
                os.environ["REVISION"])
if not any(release.glob("*.safetensors")):
    sys.exit("ERROR: no weights (*.safetensors) in the release download. Re-run; it resumes.")

cfg = json.loads((release / "maya3_config.json").read_text())
codec = (cfg.get("audio") or {}).get("codec") or "kyutai/mimi"
speaker = (cfg.get("speaker_encoder") or {}).get("repo") or "speechbrain/spkrec-ecapa-voxceleb"
fetch(codec, "mimi", ["config.json", "model.safetensors", "preprocessor_config.json"],
      ["config.json", "model.safetensors"])
fetch(speaker, "ecapa", ["embedding_model.ckpt", "hyperparams.yaml"], ["embedding_model.ckpt"])
PYEOF

echo
echo "done. $(du -sh "$DEST" | cut -f1) in $DEST"
echo
echo "The slot reads these at /models/{maya2-native,mimi,ecapa} -- this folder's"
echo "models/ bind-mounted read-only. If model-server/.env overrides MAYA_MODEL_PATH,"
echo "MAYA_MIMI_DIR or MAYA_ECAPA_DIR, those win over the compose defaults."
