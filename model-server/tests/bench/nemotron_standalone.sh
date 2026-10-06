#!/bin/sh
# Run indic-nemotron as a standalone container, beside the live stack, to test a
# checkpoint before it goes anywhere near a call.
#
#   GPU=1 PORT=8200 sh model-server/tests/bench/nemotron_standalone.sh up
#   sh model-server/tests/bench/nemotron_standalone.sh check   # which Bhili loaded
#   sh model-server/tests/bench/nemotron_standalone.sh logs
#   sh model-server/tests/bench/nemotron_standalone.sh down
#
# Why not `docker compose -p something-else up`: the base compose file hardcodes
# container_name (voicera_model_stt, voicera_model_gateway), so a second project
# collides with the live one by name. And why not a hand-written `docker run`:
# then the test runs with whatever env someone remembered to type, which is the
# bug this repo keeps shipping. So the environment is taken from
# `docker compose config` -- the overlay's resolved values, exactly what the
# live slot would get -- and only the container around it is ours.
#
# Knobs (all optional):
#   GPU         card index                                   default 1
#   PORT        published on 127.0.0.1 only                  default 8200
#   MODELS      host dir holding the checkpoints             default this checkout's
#               (point it at the live checkout's models/ to reuse its multilingual
#                weights instead of downloading 2.4 GB again)
#   ENV_FILE    .env to resolve against, e.g. the live model-server/.env
#   NAME        container name                               default nemotron_standalone
#   NEMOTRON_BHILI_NEMO_PATH etc. -- any overlay variable, passed through to Compose
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
MS=$(cd "$HERE/../.." && pwd)                       # model-server/
SLOT="$MS/stt/indic-nemotron"

GPU=${GPU:-1}
PORT=${PORT:-8200}
MODELS=${MODELS:-"$SLOT/models"}
NAME=${NAME:-nemotron_standalone}
# A tag of its own: building over voicera/model-stt:indic-nemotron would hand
# the live container this image on its next recreate.
IMAGE=voicera/model-stt:indic-nemotron-standalone

cmd=${1:-up}

resolved_env() {
  set -- -f "$MS/compose.model-server.yml" -f "$SLOT/compose.extra.yml"
  [ -n "${ENV_FILE:-}" ] && set -- --env-file "$ENV_FILE" "$@"
  STT_MODEL=indic-nemotron docker compose "$@" --project-directory "$MS" \
    --profile stt config --format json |
  python3 -c '
import json, sys
env = json.load(sys.stdin)["services"]["stt"]["environment"]
for k, v in sorted(env.items()):
    if v is not None and "\n" not in str(v):
        print(f"{k}={v}")
'
}

case "$cmd" in
  up)
    [ -d "$MODELS/indic-asr-nemotron-600m" ] || {
      echo "ERROR: no checkpoints under $MODELS -- run fetch.sh first, or set MODELS" >&2
      exit 1; }
    if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
      echo "ERROR: $NAME already exists; '$0 down' first" >&2; exit 1
    fi
    envfile=$(mktemp)
    trap 'rm -f "$envfile"' EXIT
    resolved_env > "$envfile"
    echo "--- environment (from docker compose config)"
    cat "$envfile"

    bhili=$(sed -n 's/^BHILI_NEMO_PATH=//p' "$envfile")
    host_bhili="$MODELS/${bhili#/models/}"
    if [ ! -f "$host_bhili" ]; then
      echo "ERROR: $host_bhili does not exist." >&2
      echo "The engine would not fail on this -- it would fall back to another Bhili" >&2
      echo "checkpoint, or to the multilingual model -- so this script does." >&2
      exit 1
    fi

    echo "--- building $IMAGE"
    docker build -q -t "$IMAGE" "$SLOT"

    # On ace-h200 the cards run Exclusive Process behind MPS: attach as a client
    # or the container cannot get a CUDA context. Same detection as compose-files.sh.
    set -- --gpus "device=$GPU"
    pipe=${MPS_PIPE_DIR:-/tmp/nvidia-mps-gpu$GPU}
    if [ -e "$pipe/control" ]; then
      echo "--- MPS daemon found at $pipe; attaching as a client"
      set -- "$@" --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 \
        -v "$pipe:/tmp/nvidia-mps" -e CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps \
        -v "${MPS_LOG_DIR:-/tmp/nvidia-mps-log-gpu$GPU}:/tmp/nvidia-mps-log" \
        -e CUDA_MPS_LOG_DIRECTORY=/tmp/nvidia-mps-log
    fi

    docker run -d --name "$NAME" "$@" \
      --env-file "$envfile" \
      -v "$MODELS:/models:ro" \
      -p "127.0.0.1:$PORT:8000" \
      "$IMAGE" >/dev/null
    echo "--- started $NAME on GPU $GPU, http://127.0.0.1:$PORT"
    echo "Loading takes a few minutes. Then:  sh $0 check"
    ;;

  check)
    echo "--- load lines (the only place that says WHICH checkpoint loaded)"
    docker logs "$NAME" 2>&1 | grep -E '\[Engine\] (Loading|Warning)' || echo "(nothing yet -- still starting?)"
    echo
    echo "--- /health"
    python3 - "$PORT" <<'PY'
import json, sys, urllib.request
try:
    h = json.load(urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=5))
except Exception as e:
    sys.exit(f"not answering yet: {e}")
print(json.dumps({k: h.get(k) for k in ("status", "models_loaded", "streaming")}, indent=2))
ok = (h.get("models_loaded") or {}).get("bhili") and \
     (h.get("streaming") or {}).get("att_context_size") == [96, 3]
print("\nOK" if ok else "\nNOT OK: expected bhili loaded and att_context_size [96, 3]")
sys.exit(0 if ok else 1)
PY
    ;;

  logs) docker logs -f "$NAME" ;;
  down) docker rm -f "$NAME" ;;
  *) echo "usage: $0 up|check|logs|down" >&2; exit 2 ;;
esac
