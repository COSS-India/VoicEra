#!/bin/bash
# =============================================================================
# model-server — setup & start
#
# Configure STT/TTS/LLM slots, fetch weights, build images, and start the
# gateway stack. Model-server only — no backend, V2V, or frontend.
#
# Usage:
#   ./scripts/model-server-setup.sh
#
# Optional env vars (skip menus when set):
#   STT_MODEL=<id>         folder under stt/  (empty = no STT)
#   TTS_MODEL=<id>         folder under tts/  (empty = no TTS)
#   LLM_MODEL=<id>         folder under llm/  (empty = no LLM)
#   HF_TOKEN=xxx           HuggingFace token (needed for gated TTS tokenizers)
#   GPU_DEVICE_IDS=0       which GPU to attach (default: from .env or 0)
#   USE_SHARED_HF_CACHE=1  reuse an existing HF cache via compose.shared-hf-cache.yml
#   SKIP_BUILD=1           configure only; do not build images
#   SKIP_START=1           build but do not start containers
# =============================================================================
set -e

# This script lives in scripts/ with every other runnable; the stack it drives
# lives in model-server/. Everything below is $MS_DIR-relative, so this line is
# the only place that knows the distance between the two.
MS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../model-server" && pwd)"

HF_TOKEN="${HF_TOKEN:-}"
USE_SHARED_HF_CACHE="${USE_SHARED_HF_CACHE:-}"
SKIP_BUILD="${SKIP_BUILD:-}"
SKIP_START="${SKIP_START:-}"
STT_SEL="${STT_MODEL-__ask__}"
TTS_SEL="${TTS_MODEL-__ask__}"
LLM_SEL="${LLM_MODEL-__ask__}"

log()  { echo -e "\n\033[1;32m[model-server]\033[0m $1"; }
ok()   { echo -e "\033[1;34m  ✓\033[0m $1"; }
err()  { echo -e "\033[1;31m[ERROR]\033[0m $1"; exit 1; }
# Unlike err, this does not exit: something the operator should know about, but
# which does not stop the install.
warn() { echo -e "\033[1;33m  !\033[0m $1"; }
ask()  { read -r -p "  $1: " "$2"; }

# Which models can fill a slot? One folder per model under stt/, tts/, llm/.
list_slot_models() {
  [ -d "$MS_DIR/$1" ] || return 0
  find "$MS_DIR/$1" -mindepth 1 -maxdepth 1 -type d \
       -not -name '_*' -not -name '.*' -printf '%f\n' 2>/dev/null | sort
}

# Present the folders as a menu and set $3 to the chosen id ("" for none).
pick_model() {
  local slot="$1" label="$2" var="$3"
  local options=() choice i=1
  while IFS= read -r m; do [ -n "$m" ] && options+=("$m"); done < <(list_slot_models "$slot")

  if [ ${#options[@]} -eq 0 ]; then
    echo -e "  \033[2m$label: no models available in $slot/\033[0m"
    eval "$var=''"
    return
  fi

  echo ""
  echo -e "  \033[1;37m$label\033[0m"
  for m in "${options[@]}"; do
    echo "    $i) $m"
    i=$((i + 1))
  done
  echo "    0) none"
  read -r -p "  Choose [1]: " choice
  choice="${choice:-1}"

  if [ "$choice" = "0" ]; then
    eval "$var=''"
  elif [ "$choice" -ge 1 ] 2>/dev/null && [ "$choice" -le ${#options[@]} ] 2>/dev/null; then
    eval "$var=\"${options[$((choice - 1))]}\""
  else
    echo "  Pick a number from the list."
    pick_model "$slot" "$label" "$var"
  fi
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || err "$1 is required but not installed"
}

echo ""
echo -e "\033[1;37m  model-server setup\033[0m"
echo -e "\033[2m  ─────────────────────────────────────────────────────\033[0m"

[ "$STT_SEL" = "__ask__" ] && pick_model stt "Speech to text" STT_SEL
[ "$TTS_SEL" = "__ask__" ] && pick_model tts "Text to speech" TTS_SEL
[ "$LLM_SEL" = "__ask__" ] && pick_model llm "Language model" LLM_SEL

[ "$STT_SEL" = "__ask__" ] && STT_SEL=""
[ "$TTS_SEL" = "__ask__" ] && TTS_SEL=""
[ "$LLM_SEL" = "__ask__" ] && LLM_SEL=""

# Gated HuggingFace weights are not a TTS-only problem any more.
#
# This used to ask only when TTS was selected, because indic-parler's tokenizer
# was the only gated thing in the repo. indic-nemotron's two checkpoints are
# both gated, so an STT-only install would never be asked for a token, and the
# model's own fetch.sh would then abort the whole setup on a credential it was
# never offered a chance to supply.
#
# Deliberately not "ask when the model needs it": setup.sh does not know which
# models need tokens and should not learn -- the menu is built by listing
# folders precisely so that adding a model needs no edit here. So it asks
# whenever a slot is filled and nothing has supplied credentials, and Enter
# skips for the models that do not care.
#
# A previous `huggingface-cli login` counts: it writes a token to the HF cache,
# which every fetcher and every container can already read.
hf_logged_in() {
  [ -f "$HOME/.cache/huggingface/token" ] || [ -f "${HF_HOME:-$HOME/.cache/huggingface}/token" ]
}

if [ -n "$STT_SEL$TTS_SEL$LLM_SEL" ] && [ -z "$HF_TOKEN" ] \
   && [ -z "$USE_SHARED_HF_CACHE" ] && ! hf_logged_in; then
  echo ""
  echo "  Some checkpoints are gated on HuggingFace and need a token with access"
  echo "  granted on the model page. Press Enter to skip if the model you picked"
  echo "  does not need one -- its fetch.sh will say so if it does."
  ask "HuggingFace token (or Enter to skip)" HF_TOKEN
fi

# Exported so each model's fetch.sh -- run as a child process below -- can see
# it. Without this the token reached the containers via .env but never the
# downloads, so a gated fetch failed while the token sat right there.
export HF_TOKEN

MODEL_PROFILES=""
[ -n "$STT_SEL" ] && MODEL_PROFILES="$MODEL_PROFILES,stt"
[ -n "$TTS_SEL" ] && MODEL_PROFILES="$MODEL_PROFILES,tts"
[ -n "$LLM_SEL" ] && MODEL_PROFILES="$MODEL_PROFILES,llm"
MODEL_PROFILES="${MODEL_PROFILES#,}"

echo ""
echo -e "  STT: ${STT_SEL:-none}  |  TTS: ${TTS_SEL:-none}  |  LLM: ${LLM_SEL:-none}"
read -r -p "  Proceed? [Y/n]: " _ok
[ "$_ok" = "n" ] && exit 0

# ── Prerequisites ────────────────────────────────────────────────────────────
log "Checking prerequisites"

require_command docker
docker compose version >/dev/null 2>&1 || err "docker compose plugin is required"
ok "Docker ready"

if [ -n "$MODEL_PROFILES" ]; then
  if ! docker info 2>/dev/null | grep -q nvidia; then
    if ! command -v nvidia-smi >/dev/null 2>&1; then
      err "GPU models selected but nvidia-smi is not available"
    fi
    ok "WARNING: NVIDIA Container Toolkit may not be configured — GPU containers might fail"
  else
    ok "NVIDIA runtime available"
  fi
  nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader 2>/dev/null \
    | while read -r line; do ok "GPU: $line"; done || true
fi

# ── Model weights & per-model env ───────────────────────────────────────────
NEMO_DIR=""

if [ -n "$STT_SEL" ]; then
  STT_DIR="$MS_DIR/stt/$STT_SEL"
  [ -d "$STT_DIR" ] || err "STT model folder not found: stt/$STT_SEL"

  # indic-conformer needs the NeMo fork as a build context before the image exists.
  if [ "$STT_SEL" = "indic-conformer" ]; then
    NEMO_DIR="${NEMO_CONTEXT_PATH:-$HOME/ai4bharat_nemo}"
    if [ ! -d "$NEMO_DIR" ]; then
      git clone --branch nemo-v2 --depth 1 https://github.com/AI4Bharat/NeMo.git "$NEMO_DIR"
      ok "NeMo fork cloned to $NEMO_DIR"
    else
      ok "NeMo fork already present at $NEMO_DIR"
    fi
  fi

  [ -f "$STT_DIR/fetch.sh" ] && bash "$STT_DIR/fetch.sh"

  # A model folder's own .env, for the models that read one.
  #
  # The conformer-specific keys are written only for conformer. They used to be
  # written for whatever filled the slot, which pointed every STT model at
  # IndicConformer.nemo -- harmless for a model that ignores .env, and a
  # checkpoint path to a file that does not exist for one that does not.
  #
  # Everything else a model needs comes from compose: the slot's overlay is
  # where a model declares its own configuration, and it applies whether or not
  # the model reads dotenv.
  {
    echo "PORT=8001"
    echo "HF_TOKEN=$HF_TOKEN"
    if [ "$STT_SEL" = "indic-conformer" ]; then
      echo "BHILI_ENABLE=no"
      echo "INDIC_NEMO_PATH=$STT_DIR/models/IndicConformer.nemo"
    fi
  } > "$STT_DIR/.env"
  ok "STT ready ($STT_SEL)"
fi

if [ -n "$TTS_SEL" ]; then
  TTS_DIR="$MS_DIR/tts/$TTS_SEL"
  [ -d "$TTS_DIR" ] || err "TTS model folder not found: tts/$TTS_SEL"

  [ -f "$TTS_DIR/fetch.sh" ] && bash "$TTS_DIR/fetch.sh"
  cat > "$TTS_DIR/.env" << ENVEOF
CHECKPOINT_PATH_DEFAULT=$TTS_DIR/checkpoints
BHILI_ENABLE=no
PORT=8002
HF_TOKEN=$HF_TOKEN
ENVEOF
  ok "TTS ready ($TTS_SEL)"
fi

if [ -n "$LLM_SEL" ]; then
  LLM_DIR="$MS_DIR/llm/$LLM_SEL"
  [ -d "$LLM_DIR" ] || err "LLM model folder not found: llm/$LLM_SEL"
  [ -f "$LLM_DIR/fetch.sh" ] && bash "$LLM_DIR/fetch.sh"
  ok "LLM ready ($LLM_SEL)"
fi

# ── Compose config ───────────────────────────────────────────────────────────
[ -f "$MS_DIR/.env" ] || cp "$MS_DIR/.env.example" "$MS_DIR/.env"

# The compose file list is built by compose-files.sh, further down -- after
# .env holds the selections it reads. Anything that starts or stops this stack
# has to produce the same list, and building it here as well is how they drift.

# Write KEY=VALUE into .env: replace the line if it is there in any form,
# append it if it is not.
#
# Every write below used to be `sed -i "s|^KEY=.*|KEY=new|"`, which silently
# does nothing when the key is absent -- so an .env predating a variable never
# gained it. Two of them were also written against the wrong shape entirely:
#
#   USE_SHARED_HF_CACHE matched only `^# *KEY=`, while .env.example ships the
#   key uncommented. The choice was therefore never persisted and the overlay
#   never applied -- not even on the run that asked for it -- while the flag was
#   still honoured in-process to skip the HF-token prompt. The operator was told
#   nothing and the gated tokeniser download came back.
#
#   MPS_PIPE_DIR had the mirror-image bug: it matched only the commented form,
#   so the first run uncommented it and every later run left the value pointing
#   at the previous GPU. That is exactly the "GPU 3 with GPU 1's pipe" mismatch
#   compose.mps.yml was written to prevent, reintroduced one layer up.
#
# The value goes through the environment rather than into a sed expression, so
# it cannot break on `|`, `&` or a backslash.
set_env() {
  _key=$1
  _value=$2
  _file="$MS_DIR/.env"
  [ -f "$_file" ] || : > "$_file"
  SET_ENV_KEY="$_key" SET_ENV_VALUE="$_value" awk '
    BEGIN { key = ENVIRON["SET_ENV_KEY"]; value = ENVIRON["SET_ENV_VALUE"]; done = 0 }
    {
      line = $0
      sub(/^# */, "", line)
      if (index(line, key "=") == 1) {
        if (!done) { print key "=" value; done = 1 }
        next
      }
      print
    }
    END { if (!done) print key "=" value }
  ' "$_file" > "$_file.tmp" && mv "$_file.tmp" "$_file"
}

GPU_IDS="${GPU_DEVICE_IDS:-}"
if [ -z "$GPU_IDS" ] && [ -f "$MS_DIR/.env" ]; then
  GPU_IDS=$(grep -E '^GPU_DEVICE_IDS=' "$MS_DIR/.env" | cut -d= -f2- || true)
fi
GPU_IDS="${GPU_IDS:-0}"

set_env STT_MODEL "$STT_SEL"
set_env TTS_MODEL "$TTS_SEL"
set_env LLM_MODEL "$LLM_SEL"
set_env COMPOSE_PROFILES "$MODEL_PROFILES"
set_env HF_TOKEN "$HF_TOKEN"
set_env GPU_DEVICE_IDS "$GPU_IDS"

# Leftover from an old native-mode experiment — localhost upstreams break the
# gateway container, which must reach STT/TTS/LLM by Compose service name.
sed -i '/^RUN_MODE=/d; /^STT_UPSTREAM=http:\/\/127\.0\.0\.1/d' "$MS_DIR/.env"

if [ -n "$NEMO_DIR" ]; then
  set_env NEMO_CONTEXT_PATH "$NEMO_DIR"
fi

# Persist the shared-cache choice. It was a setup-time variable only, so a
# later `make ms-up` or restart silently dropped the overlay and the gated
# tokeniser download came back.
set_env USE_SHARED_HF_CACHE "${USE_SHARED_HF_CACHE:-}"

# ---- MPS -------------------------------------------------------------------
# A GPU in Exclusive Process mode can only be shared through an MPS daemon; a
# GPU in the ordinary Default mode needs none of it. Detected, not configured:
# the daemon publishes a `control` pipe, and that file existing is the fact.
# Guessing wrong is silent either way -- attach with no daemon and the client
# finds nothing; skip it on an Exclusive Process GPU and the container never
# gets a CUDA context.
MPS_PIPE_DIR="${MPS_PIPE_DIR:-/tmp/nvidia-mps-gpu${GPU_IDS}}"
MPS_LOG_DIR="${MPS_LOG_DIR:-/tmp/nvidia-mps-log-gpu${GPU_IDS}}"
set_env MPS_PIPE_DIR "$MPS_PIPE_DIR"
set_env MPS_LOG_DIR "$MPS_LOG_DIR"

if [ -e "$MPS_PIPE_DIR/control" ] || pgrep -x nvidia-cuda-mps-control >/dev/null 2>&1; then
  ok "MPS daemon found at $MPS_PIPE_DIR -- attaching as a client"
else
  warn "No MPS daemon at $MPS_PIPE_DIR -- running without it."
  warn "  Correct on a GPU in Default mode. If this card is in Exclusive"
  warn "  Process mode, start the daemon first or the containers get no"
  warn "  CUDA context: nvidia-smi -q | grep -i 'compute mode'"
fi

# Now .env is complete, so the shared script can answer what to run with.
COMPOSE_FILES=$(sh "$MS_DIR/compose-files.sh")
ok "compose files:$(echo "$COMPOSE_FILES" | sed "s|$MS_DIR/||g; s| -f | |g")"

if [ -n "$TTS_SEL" ] && [ -z "$HF_TOKEN" ] && [ -z "$USE_SHARED_HF_CACHE" ]; then
  echo ""
  echo "  WARNING: TTS is enabled but no HF_TOKEN was given. ai4bharat/indic-parler-tts"
  echo "           is gated — the container may fail to start. Either supply HF_TOKEN,"
  echo "           or rerun with USE_SHARED_HF_CACHE=1 to reuse an existing cache."
fi

if [ -z "$MODEL_PROFILES" ]; then
  log "No model slots selected — gateway only"
  COMPOSE_PROFILES="" docker compose $COMPOSE_FILES --project-directory "$MS_DIR" up -d gateway
  _port=$(grep -E '^GATEWAY_PORT=' "$MS_DIR/.env" | cut -d= -f2)
  # `|| echo 8100` never fired here: cut succeeds on empty input, so a missing
  # GATEWAY_PORT printed "started on port " with nothing after it.
  ok "Gateway started on port ${_port:-8100}"
  exit 0
fi

# ── Build & start ────────────────────────────────────────────────────────────
if [ -z "$SKIP_BUILD" ]; then
  log "Building model images (first build can take 20-40 min)"
  docker compose $COMPOSE_FILES --project-directory "$MS_DIR" build
  ok "Model images built for slots: $MODEL_PROFILES"
fi

if [ -z "$SKIP_START" ]; then
  log "Starting containers"
  docker compose $COMPOSE_FILES --project-directory "$MS_DIR" up -d
  ok "Stack started"
fi

GATEWAY_PORT=$(grep -E '^GATEWAY_PORT=' "$MS_DIR/.env" | cut -d= -f2)
GATEWAY_PORT="${GATEWAY_PORT:-8100}"

echo ""
echo -e "\033[1;36m  ══════════════════════════════════════\033[0m"
echo -e "\033[1;32m         ✓  model-server is up\033[0m"
echo -e "\033[1;36m  ══════════════════════════════════════\033[0m"
echo ""
echo "  Demo:     http://localhost:${GATEWAY_PORT}/demo"
echo "  Gateway:  http://localhost:${GATEWAY_PORT}"
echo "  Health:   curl http://localhost:${GATEWAY_PORT}/health"
echo "  Models:   curl http://localhost:${GATEWAY_PORT}/models"
echo ""
echo "  Logs:     make ms-logs"
echo "  Stop:     make ms-down     (or ./scripts/model-server-stop.sh)"
