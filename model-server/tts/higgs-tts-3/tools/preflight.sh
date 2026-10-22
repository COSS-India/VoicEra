#!/bin/sh
# Read-only checks before starting the standalone Higgs test stack on a shared
# GPU box. Changes nothing; prints what it found and a GO / NO-GO at the end.
#
#   cd model-server
#   GPU_DEVICE_IDS=1 sh tts/higgs-tts-3/tools/preflight.sh
#
# Checks: the GPU has room for the sidecar's memory caps, the MPS situation
# (and so whether compose.mps.yml is needed), that none of the test stack's
# names are taken by something else, the optional localhost port, disk space
# for the images and checkpoint, and whether an API key will be required.
set -u

GPU=${TTS_GPU_DEVICE_IDS:-${GPU_DEVICE_IDS:-0}}
PORT=${HIGGS_TEST_PORT:-18202}
# Sum of the three per-stage fractions in compose.standalone.yml.
ENGINE=${HIGGS_ENGINE_GPU_MEMORY_FRACTION:-0.12}
VOCODER=${HIGGS_VOCODER_GPU_MEMORY_FRACTION:-0.03}
ENCODER=${HIGGS_ENCODER_GPU_MEMORY_FRACTION:-0.02}
NEED_DISK_GB=45     # sglang-omni image (~30 GB) + checkpoint (~10 GB) + slack

fail=0; warn=0
ok()   { echo "  ok    $*"; }
bad()  { echo "  STOP  $*"; fail=1; }
note() { echo "  warn  $*"; warn=1; }

# docker may need sudo on this box; use whichever works, read-only either way.
DOCKER=docker
if ! docker ps >/dev/null 2>&1; then
  if sudo -n docker ps >/dev/null 2>&1 || sudo docker ps >/dev/null 2>&1; then
    DOCKER="sudo docker"
  else
    echo "cannot run docker (with or without sudo)"; exit 1
  fi
fi

echo "GPU $GPU"
if command -v nvidia-smi >/dev/null 2>&1; then
  line=$(nvidia-smi -i "$GPU" --query-gpu=name,memory.total,memory.used,compute_mode \
         --format=csv,noheader,nounits 2>&1)
  echo "  $line"
  total=$(echo "$line" | cut -d, -f2 | tr -d ' ')
  used=$(echo "$line" | cut -d, -f3 | tr -d ' ')
  mode=$(echo "$line" | cut -d, -f4 | tr -d ' ')
  need=$(awk "BEGIN{printf \"%d\", ($ENGINE+$VOCODER+$ENCODER)*$total}")
  free=$((total - used))
  echo "  needs ~${need} MiB (fractions $ENGINE + $VOCODER + $ENCODER of ${total} MiB); free ${free} MiB"
  if [ "$free" -lt "$need" ]; then
    bad "not enough free memory on GPU $GPU; lower HIGGS_*_GPU_MEMORY_FRACTION or pick another GPU"
  elif [ "$free" -lt $((need + need / 2)) ]; then
    note "free memory is tight: under 1.5x what Higgs reserves, and whatever else uses this GPU may grow"
  else
    ok "memory"
  fi
else
  bad "nvidia-smi not found"; mode=unknown
fi

echo "MPS"
pipe=${TTS_MPS_PIPE_DIR:-${MPS_PIPE_DIR:-/tmp/nvidia-mps-gpu$GPU}}
if [ -e "$pipe/control" ] || pgrep -x nvidia-cuda-mps-control >/dev/null 2>&1; then
  if [ -e "$pipe/control" ]; then
    ok "daemon found at $pipe: INCLUDE -f tts/higgs-tts-3/compose.mps.yml"
  else
    note "an MPS daemon runs but $pipe/control is missing; set TTS_MPS_PIPE_DIR to its pipe directory"
  fi
elif [ "${mode:-}" = "Exclusive_Process" ]; then
  bad "GPU $GPU is Exclusive_Process with no MPS daemon: a second CUDA process cannot attach"
else
  ok "no daemon (compute mode ${mode:-?}): leave compose.mps.yml OUT"
fi

echo "Names"
for c in voicera_higgs_test_sglang voicera_higgs_test_tts voicera_higgs_test_tunnel; do
  if $DOCKER container inspect "$c" >/dev/null 2>&1; then
    proj=$($DOCKER container inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$c")
    if [ "$proj" = "voicera-higgs-test" ]; then note "$c exists from an earlier test run (fine; up replaces it)"
    else bad "container $c exists and belongs to '$proj'"; fi
  else ok "container $c is free"; fi
done
for v in "${HIGGS_HF_CACHE_VOLUME:-voicera-higgs-test_hf_cache}"; do
  if $DOCKER volume inspect "$v" >/dev/null 2>&1; then note "volume $v exists (reused: the checkpoint is not downloaded twice)"
  else ok "volume $v is free"; fi
done
if $DOCKER network inspect voicera-higgs-test_higgs_net >/dev/null 2>&1; then note "network voicera-higgs-test_higgs_net exists from an earlier run"
else ok "network voicera-higgs-test_higgs_net is free"; fi
if $DOCKER image inspect cloudflare/cloudflared:latest >/dev/null 2>&1; then
  ok "cloudflared image is cached (the tunnel will not pull, so the box's tunnels are untouched)"
else
  note "cloudflare/cloudflared:latest is not cached; --profile tunnel will pull it"
fi

echo "Port (only with compose.standalone.localport.yml)"
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$PORT\$"; then
  note "127.0.0.1:$PORT is in use: set HIGGS_TEST_PORT to something free if you use the localport overlay"
else
  ok "$PORT is free"
fi

echo "Disk"
root=$($DOCKER info -f '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)
avail=$(df -BG --output=avail "$root" 2>/dev/null | tail -1 | tr -dc 0-9)
if [ -n "$avail" ] && [ "$avail" -lt "$NEED_DISK_GB" ]; then
  bad "only ${avail} GB free under $root; the images and checkpoint need ~${NEED_DISK_GB} GB"
else
  ok "${avail:-?} GB free under $root"
fi

echo "API key"
if [ -n "${HIGGS_TEST_API_KEY:-}" ]; then ok "HIGGS_TEST_API_KEY is set: /v1/* will require it"
else note "no HIGGS_TEST_API_KEY: the demo and API are OPEN to anyone with the tunnel URL"; fi

echo
if [ "$fail" -ne 0 ]; then echo "NO-GO: fix the STOP lines above."; exit 1; fi
[ "$warn" -ne 0 ] && echo "GO, with the warnings above." || echo "GO."
