#!/bin/bash
# Stop the model-server compose stack started by scripts/model-server-setup.sh.
#
# The file list comes from compose-files.sh, not from here. This script used to
# rebuild it by hand and got a shorter answer: it missed compose.mps.yml,
# compose.shared-hf-cache.yml and any per-model MPS overlay, so `down` was
# working from a different view of the stack than `up` had. compose-files.sh
# says in its own header that anything starting or stopping this stack has to
# agree on all three inputs -- this was the one caller that did not, and
# tests/test_mps.py only checked the Makefile and setup.sh, so nothing caught it.
#
# It also did `set -a && source .env`, executing as shell the file
# compose-files.sh explicitly refuses to exec. That was redundant as well as
# unsafe: --project-directory already makes Compose load it.
set -e
# This script lives in scripts/ with every other runnable; the stack it drives
# lives in model-server/. Everything below is $MS_DIR-relative, so this line is
# the only place that knows the distance between the two.
MS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../model-server" && pwd)"

COMPOSE_FILES=$(sh "$MS_DIR/compose-files.sh")

echo "Stopping model-server containers..."
docker compose $COMPOSE_FILES --project-directory "$MS_DIR" down
echo "Done."
