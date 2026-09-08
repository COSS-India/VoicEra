#!/usr/bin/env bash
# Stop the Voicera Docker stack started via docker-compose.yaml.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

[[ -f docker-compose.yaml ]] || {
    echo "Error: docker-compose.yaml not found at repo root." >&2
    exit 1
}

docker compose -f docker-compose.yaml down "$@"
