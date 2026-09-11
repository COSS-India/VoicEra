#!/usr/bin/env bash
# One-command Voicera install: fetches the compose stack + helper scripts
# from GitHub and starts it. No git clone needed.
#
#   curl -fsSL https://raw.githubusercontent.com/COSS-India/VoicEra/main/scripts/install.sh | bash
set -euo pipefail

REPO="COSS-India/VoicEra"
BRANCH="${VOICERA_BRANCH:-main}"
RAW="https://raw.githubusercontent.com/${REPO}/${BRANCH}"
DIR="${VOICERA_DIR:-voicera}"

mkdir -p "$DIR/scripts"
cd "$DIR"

echo "Fetching Voicera compose stack (branch: $BRANCH)..."
curl -fsSL -o docker-compose.yaml "$RAW/docker-compose.yaml"
curl -fsSL -o .env.example "$RAW/.env.example"
curl -fsSL -o scripts/start-application-services.sh "$RAW/scripts/start-application-services.sh"
curl -fsSL -o scripts/stop-application-services.sh "$RAW/scripts/stop-application-services.sh"
chmod +x scripts/start-application-services.sh scripts/stop-application-services.sh

./scripts/start-application-services.sh
