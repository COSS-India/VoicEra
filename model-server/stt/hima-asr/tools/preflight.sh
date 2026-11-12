#!/bin/sh
# Read-only checks before starting the standalone Hima test stack on a shared
# GPU box. Changes nothing; prints what it found and a GO / NO-GO at the end.
#
#   cd model-server
#   sh stt/hima-asr/tools/preflight.sh
#
# What "nothing else is affected" needs to be true, checked one by one:
#   - this checkout is its own folder, not one another stack runs from
#   - every container, image, network and port the stack will create is free,
#     or already belongs to this test project from an earlier run
#   - the GPU has room for Hima's memory cap with margin, and no MPS daemon
#     needs attaching to
#   - the images it builds FROM are either cached or will be pulled fresh --
#     pulling never retags an image another stack runs from
#   - the cloudflared image is cached, so the tunnel does not pull a new
#     `latest` under the box's other tunnels
#   - there is disk for the image and the checkpoint
set -u

HERE=$(cd "$(dirname "$0")/.." && pwd)            # stt/hima-asr
MS=$(cd "$HERE/../.." && pwd)                       # model-server
GPU=${HIMA_TEST_GPU:-1}
PORT=${HIMA_TEST_PORT:-18201}
CAP_GB=${HIMA_MAX_GPU_MEMORY_GB:-8}
NEED_DISK_GB=25     # CUDA runtime + torch image (~12 GB) + checkpoint (~1 GB) + slack
PROJECT=voicera-hima-test

fail=0; warn=0
ok()   { echo "  ok    $*"; }
bad()  { echo "  STOP  $*"; fail=1; }
note() { echo "  warn  $*"; warn=1; }

DOCKER=docker
if ! docker ps >/dev/null 2>&1; then
  if sudo -n docker ps >/dev/null 2>&1 || sudo docker ps >/dev/null 2>&1; then
    DOCKER="sudo docker"
  else
    echo "cannot run docker (with or without sudo)"; exit 1
  fi
fi

echo "Checkout"
echo "  $MS"
running_here=$($DOCKER ps -a --format '{{.Names}} {{.Label "com.docker.compose.project.working_dir"}}' \
  | awk -v d="$MS" '$2 == d && $1 !~ /^voicera_hima_test_/ {print $1}')
if [ -n "$running_here" ]; then
  bad "other containers were started from this folder: $(echo $running_here). Use a fresh clone."
else
  ok "no other stack runs from this folder"
fi
branch=$(git -C "$MS" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
[ "$branch" = "feature/hima-asr-stt" ] && ok "branch $branch" || note "branch is '$branch', not feature/hima-asr-stt"

echo "GPU $GPU"
if command -v nvidia-smi >/dev/null 2>&1; then
  line=$(nvidia-smi -i "$GPU" --query-gpu=name,memory.total,memory.used,compute_mode \
         --format=csv,noheader,nounits 2>&1)
  echo "  $line"
  total=$(echo "$line" | cut -d, -f2 | tr -d ' ')
  used=$(echo "$line" | cut -d, -f3 | tr -d ' ')
  mode=$(echo "$line" | cut -d, -f4 | tr -d ' ')
  free=$((total - used))
  need=$((CAP_GB * 1024))
  echo "  Hima is capped at ${CAP_GB} GB (HIMA_MAX_GPU_MEMORY_GB); free ${free} MiB"
  if [ "$free" -lt "$need" ]; then
    bad "not enough free memory on GPU $GPU for the cap"
  elif [ "$free" -lt $((need * 3)) ]; then
    note "under 3x the cap is free; the models already on this GPU have little headroom left"
  else
    ok "memory"
  fi
  if [ "$mode" = "Exclusive_Process" ]; then
    if [ -e "/tmp/nvidia-mps-gpu$GPU/control" ] || pgrep -x nvidia-cuda-mps-control >/dev/null 2>&1; then
      bad "GPU $GPU is Exclusive_Process behind MPS; compose.standalone.yml has no MPS overlay yet"
    else
      bad "GPU $GPU is Exclusive_Process with no MPS daemon: a second CUDA process cannot attach"
    fi
  else
    ok "compute mode $mode: no MPS to attach to"
  fi
else
  bad "nvidia-smi not found"
fi

echo "Names"
for c in voicera_hima_test_stt voicera_hima_test_gateway voicera_hima_test_tunnel; do
  if $DOCKER container inspect "$c" >/dev/null 2>&1; then
    proj=$($DOCKER container inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$c")
    if [ "$proj" = "$PROJECT" ]; then note "$c exists from an earlier test run (fine; up replaces it)"
    else bad "container $c exists and belongs to '$proj'"; fi
  else ok "container $c is free"; fi
done
net=${PROJECT}_default
if $DOCKER network inspect "$net" >/dev/null 2>&1; then
  proj=$($DOCKER network inspect -f '{{index .Labels "com.docker.compose.project"}}' "$net")
  [ "$proj" = "$PROJECT" ] && note "network $net exists from an earlier run" \
                           || bad "network $net exists and belongs to '$proj'"
else ok "network $net is free"; fi
for img in voicera-hima-test/stt:local voicera-hima-test/gateway:local; do
  if $DOCKER image inspect "$img" >/dev/null 2>&1; then
    users=$($DOCKER ps -a --filter "ancestor=$img" --format '{{.Names}}' | grep -v '^voicera_hima_test_' || true)
    [ -z "$users" ] && note "image $img exists from an earlier run (rebuilt in place)" \
                    || bad "image $img is used by: $users"
  else ok "image $img is free"; fi
done

echo "Base images (pulled if missing; a pull adds an image, it never changes one in use)"
for img in nvidia/cuda:13.0.1-runtime-ubuntu24.04 python:3.12-slim; do
  $DOCKER image inspect "$img" >/dev/null 2>&1 && ok "$img cached" || note "$img will be pulled"
done
if $DOCKER image inspect cloudflare/cloudflared:latest >/dev/null 2>&1; then
  ok "cloudflared:latest cached (pull_policy: missing -- the box's tunnels keep their image)"
else
  note "cloudflared:latest is not cached; --profile tunnel will pull it"
fi

echo "Port"
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$PORT\$"; then
  owner=$($DOCKER ps --filter "publish=$PORT" --format '{{.Names}}')
  case "$owner" in
    voicera_hima_test_gateway) note "127.0.0.1:$PORT is this stack's gateway from an earlier run" ;;
    *) bad "127.0.0.1:$PORT is in use${owner:+ by $owner}; set HIMA_TEST_PORT to a free port" ;;
  esac
else
  ok "127.0.0.1:$PORT is free"
fi

echo "Disk"
root=$($DOCKER info -f '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)
avail=$(df -BG --output=avail "$root" 2>/dev/null | tail -1 | tr -dc 0-9)
if [ -z "$avail" ]; then
  note "could not read free space under $root (try: sudo df -h $root); need ~${NEED_DISK_GB} GB"
elif [ "$avail" -lt "$NEED_DISK_GB" ]; then
  bad "only ${avail} GB free under $root; the image and checkpoint need ~${NEED_DISK_GB} GB"
else
  ok "${avail} GB free under $root"
fi
here_avail=$(df -BG --output=avail "$HERE" 2>/dev/null | tail -1 | tr -dc 0-9)
[ -n "$here_avail" ] && [ "$here_avail" -lt 3 ] && bad "under 3 GB free for the checkpoint at $HERE" \
  || ok "${here_avail:-?} GB free for the checkpoint"

echo "Weights"
if [ -f "$HERE/models/hima-asr/.revision" ]; then
  ok "fetched at $(cat "$HERE/models/hima-asr/.revision")"
else
  note "not fetched yet: run sh stt/hima-asr/fetch.sh"
fi

echo
echo "Exposure: with --profile tunnel the demo and API are OPEN to anyone with the URL."
echo
if [ "$fail" -ne 0 ]; then echo "NO-GO: fix the STOP lines above."; exit 1; fi
[ "$warn" -ne 0 ] && echo "GO, with the warnings above." || echo "GO."
