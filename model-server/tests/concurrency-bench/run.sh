#!/usr/bin/env bash
# Thin wrapper over the Python scripts, driven by config.env.
#
#   ./run.sh setup      create .venv and install requirements
#   ./run.sh corpus     build the STT clips (synthesise, or import your own)
#   ./run.sh stt        STT Test A + Test B
#   ./run.sh tts        TTS Test A + Test B
#   ./run.sh runaway    TTS runaway rate at N=1 (optional)
#   ./run.sh report     write report.md for the run
#   ./run.sh all        corpus (if missing) -> stt -> tts -> report
#
# All steps of one run write to $RESULTS_ROOT/$RUN_ID. RUN_ID defaults to a
# timestamp; to run steps separately into the same folder, export it first:
#   export RUN_ID=h100-run1; ./run.sh stt; ./run.sh tts; ./run.sh report
set -Eeuo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

CONFIG="${CONFIG:-config.env}"
if [ -f "$CONFIG" ]; then
  # Values already in the environment win over the file; within the file the
  # last assignment wins, as with `source`.
  preset=" $(compgen -e | tr '\n' ' ') "
  while IFS= read -r line; do
    line="${line%%#*}"; line="${line%"${line##*[![:space:]]}"}"
    [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
    key="${line%%=*}"
    [[ "$preset" == *" $key "* ]] || eval "export $line"
  done < "$CONFIG"
elif [ "${1:-}" != "setup" ]; then
  echo "no $CONFIG -- run: cp config.example.env config.env  (then edit it)" >&2
  exit 1
fi

: "${LANGUAGE:=mr}" "${RESULTS_ROOT:=results}" "${CORPUS_DIR:=corpus/$LANGUAGE}"
export RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
OUT="$RESULTS_ROOT/$RUN_ID"
PY="${PYTHON:-$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3 )}"

common_args() {
  local a=(--language "$LANGUAGE" --levels "$LEVELS" --rounds "$ROUNDS"
           --arrival-window "$ARRIVAL_WINDOW_S" --mode "$MODE" --seed "$SEED"
           --warmup-singles "$WARMUP_SINGLES" --warmup-batches "$WARMUP_BATCHES"
           --warmup-budget "$WARMUP_BUDGET_S" --out-dir "$OUT")
  [ -n "${GPU_INDEX:-}" ] && a+=(--gpu-index "$GPU_INDEX")
  printf '%s\0' "${a[@]}"
}

log() { mkdir -p "$OUT"; tee -a "$OUT/run.log"; }

fd_check() {
  local need=$(( $(tr , '\n' <<<"$LEVELS" | sort -n | tail -1) * 2 + 64 ))
  if [ "$(ulimit -n)" != unlimited ] && [ "$(ulimit -n)" -lt "$need" ]; then
    ulimit -n "$need" 2>/dev/null || echo "WARNING: open-file limit $(ulimit -n) < $need; run 'ulimit -n $need' first" >&2
  fi
}

do_setup() {
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
  echo "ready: .venv"
}

do_corpus() {
  if [ -n "${IMPORT_WAV_DIR:-}" ]; then
    "$PY" -u make_corpus.py import --wav-dir "$IMPORT_WAV_DIR" \
      --transcripts "$IMPORT_TRANSCRIPTS" --language "$LANGUAGE" --out "$CORPUS_DIR"
  else
    "$PY" -u make_corpus.py synth --tts-url "$TTS_URL" --language "$LANGUAGE" \
      --voices "${CORPUS_VOICES:-}" --out "$CORPUS_DIR"
  fi
}

do_stt() {
  fd_check
  local args=(); while IFS= read -r -d '' x; do args+=("$x"); done < <(common_args)
  "$PY" -u stt_load.py --url "$STT_URL" --health-path "$STT_HEALTH_PATH" \
    --manifest "$CORPUS_DIR/manifest.json" --bucket "$STT_BUCKET" "${args[@]}" 2>&1 | log
}

do_tts() {
  fd_check
  local args=(); while IFS= read -r -d '' x; do args+=("$x"); done < <(common_args)
  "$PY" -u tts_load.py --url "$TTS_URL" --health-path "$TTS_HEALTH_PATH" \
    --voice "${TTS_VOICE:-}" --length "$TTS_LENGTH" "${args[@]}" 2>&1 | log
}

do_runaway() {
  "$PY" -u runaway_check.py --url "$TTS_URL" --health-path "$TTS_HEALTH_PATH" \
    --language "$LANGUAGE" --voice "${TTS_VOICE:-}" --length "$TTS_LENGTH" \
    --n "${RUNAWAY_N:-200}" --out-dir "$OUT" 2>&1 | log
}

do_report() {
  "$PY" report.py --results "$OUT" --percentile "$PASS_PERCENTILE" --rtf-threshold "$PASS_RTF"
}

case "${1:-}" in
  setup)   do_setup ;;
  corpus)  do_corpus ;;
  stt)     do_stt ;;
  tts)     do_tts ;;
  runaway) do_runaway ;;
  report)  do_report ;;
  all)
    [ -f "$CORPUS_DIR/manifest.json" ] || do_corpus
    do_stt; do_tts; do_report
    echo "results: $OUT" ;;
  *) sed -n '2,15p' "$0"; exit 1 ;;
esac
