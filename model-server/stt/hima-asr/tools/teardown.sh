#!/bin/sh
# Remove the standalone Hima test stack -- and only it.
#
#   cd model-server
#   sh stt/hima-asr/tools/teardown.sh            # containers + network
#   sh stt/hima-asr/tools/teardown.sh --images   # ...and the two images it built
#
# Deliberately NOT `docker compose down --rmi all`: that removes every image a
# service uses, including cloudflare/cloudflared:latest, which the box's other
# tunnels run from. Only the images this stack built and tagged are removed,
# by name. Base images (nvidia/cuda, python:3.12-slim) are left alone; other
# builds on the box may share them. The checkpoint in models/ is left too.
set -eu

MS=$(cd "$(dirname "$0")/../../.." && pwd)
DOCKER=docker
docker ps >/dev/null 2>&1 || DOCKER="sudo docker"

$DOCKER compose -p voicera-hima-test --project-directory "$MS" \
  -f "$MS/stt/hima-asr/compose.standalone.yml" --profile tunnel down

if [ "${1:-}" = "--images" ]; then
  for img in voicera-hima-test/stt:local voicera-hima-test/gateway:local; do
    $DOCKER image rm "$img" 2>/dev/null && echo "removed $img" || echo "$img not present"
  done
fi
echo "done. Nothing outside project voicera-hima-test was touched."
