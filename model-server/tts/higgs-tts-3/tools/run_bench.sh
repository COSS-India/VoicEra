#!/bin/sh
# Run the repo's TTS concurrency bench (tests/concurrency-bench/tts_load.py)
# against the standalone Higgs test stack, ON THE GPU HOST.
#
#   cd model-server
#   sudo sh tts/higgs-tts-3/tools/run_bench.sh
#   LEVELS=1,2,4,8 ROUNDS=1 sudo -E sh tts/higgs-tts-3/tools/run_bench.sh   # smoke run
#
# The load generator runs in a throwaway container on the stack's own network
# and talks to the adapter at http://tts:8002 directly:
#   * no host port is opened, nothing else on the box is touched;
#   * no Cloudflare tunnel in the path -- quick tunnels cap in-flight requests
#     and add an internet round trip to every one, which would be measured as
#     the model's.
# GPU memory and utilisation are sampled on the host with nvidia-smi alongside.
#
# Output: tests/concurrency-bench/results/<RUN_ID>/ -- report.md, per-request
# JSONL, gpu.csv, run.log. Paste report.md (and gpu.csv's peak) back.
set -eu

HERE=$(cd "$(dirname "$0")/../../.." && pwd)          # model-server/
BENCH="$HERE/tests/concurrency-bench"
LEVELS=${LEVELS:-1,2,4,8,16,32,64,96,128,160,192,224,256}
ROUNDS=${ROUNDS:-3}
MODE=${MODE:-both}                       # sync = Test A, random = Test B, both
LANGUAGE=${LANGUAGE:-mr}                 # prompts/<lang>.json supplies the sentence
VOICE=${VOICE:-default}                  # zero-shot until the voice clips are committed
GPU=${TTS_GPU_DEVICE_IDS:-${GPU_DEVICE_IDS:-1}}
NETWORK=${NETWORK:-voicera-higgs-test_higgs_net}
RUN_ID=${RUN_ID:-higgs-$(date +%Y%m%d-%H%M%S)}
OUT="$BENCH/results/$RUN_ID"

docker network inspect "$NETWORK" >/dev/null 2>&1 || { echo "no network $NETWORK: is the test stack up?"; exit 1; }
health=$(docker exec voicera_higgs_test_sglang python3 -c \
  "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/health',timeout=5).status)" 2>/dev/null || true)
[ "$health" = "200" ] || { echo "the sidecar is not healthy yet (docker inspect voicera_higgs_test_sglang)"; exit 1; }

# What the server is actually running with, recorded beside the numbers: the
# verdict means nothing without the configuration it was measured on.
cmdline=$(docker inspect -f '{{join .Args " "}}' voicera_higgs_test_sglang)
notes="higgs-tts-3 standalone; sidecar: $cmdline; voice=$VOICE; levels=$LEVELS"

mkdir -p "$OUT"
echo "$notes" > "$OUT/server_config.txt"
echo "run $RUN_ID -> $OUT"

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi -i "$GPU" --query-gpu=timestamp,memory.used,memory.total,utilization.gpu \
    --format=csv -l 1 > "$OUT/gpu.csv" 2>&1 &
  SAMPLER=$!
fi
# The adapter is ONE Python process relaying every stream. If it saturates a
# core, a high-N failure is the adapter's, not the model's -- and the report
# alone cannot tell the two apart. Sampled every ~2 s alongside the GPU.
( while :; do
    printf '%s, ' "$(date +%H:%M:%S)"
    docker stats --no-stream --format '{{.Name}}, {{.CPUPerc}}, {{.MemUsage}}' \
      voicera_higgs_test_tts voicera_higgs_test_sglang | tr '\n' ' '
    echo
  done > "$OUT/containers.csv" 2>&1 ) &
STATS=$!
trap 'kill ${SAMPLER:-} $STATS 2>/dev/null || true' EXIT INT TERM

# The adapter's /health has no streams_active; the bench's idle wait then
# returns at once, and its 1 s pause plus cooldown separate the rounds.
# The runaway flag is Orpheus's guard formula (chars/8 x 3 s); for Higgs it
# flags any response that long, i.e. one that did not stop by itself.
docker run --rm --name voicera_higgs_test_bench --network "$NETWORK" \
  --ulimit nofile=65536:65536 \
  -v "$BENCH":/bench -w /bench \
  python:3.12-slim sh -c "
    pip install -q --root-user-action=ignore -r requirements.txt &&
    python -u tts_load.py --url http://tts:8002 --health-path /health --voices-path /v1/voices \
      --language $LANGUAGE --voice $VOICE --style '' \
      --levels $LEVELS --rounds $ROUNDS --mode $MODE \
      --warmup-batches 8,64,256 --out-dir results/$RUN_ID \
      --note '$notes' &&
    python report.py --results results/$RUN_ID" 2>&1 | tee "$OUT/run.log"

if [ -f "$OUT/gpu.csv" ]; then
  peak=$(tail -n +2 "$OUT/gpu.csv" | awk -F', ' '{gsub(/ MiB/,"",$2); if ($2+0>m) m=$2+0} END {print m}')
  echo "GPU $GPU peak memory.used during the run: ${peak} MiB (gpu.csv has the timeline)"
fi
peak_cpu=$(grep -o 'voicera_higgs_test_tts, [0-9.]*%' "$OUT/containers.csv" | awk -F', ' '{v=$2+0; if (v>m) m=v} END {print m}')
echo "adapter peak CPU: ${peak_cpu}% (100% = one core saturated; containers.csv has the timeline)"
echo "report: $OUT/report.md"
