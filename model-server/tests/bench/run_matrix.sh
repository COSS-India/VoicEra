#!/bin/bash
# One arm of the load test: every suite against the OpenAI-spec streaming endpoint.
# $1 = arm label (e.g. "before" / "after"), used as the results filename prefix.
set -u
ARM="${1:?arm label required}"
V=/home/ubuntu/Voicera/model-server/tests/.venv-bench/bin/python
cd "$(dirname "$0")"
run() { echo; echo "=== $ARM :: $* ==="; $V sweep.py "$@"; }

run single      -n 20                                  --out "results/${ARM}_single.json"
run concurrency -n 20 --levels 1,2,4,8,12,16,24,32,48,64 --out "results/${ARM}_concurrency.json"
run arrivals    -n 20 --arrival poisson --rates 1,2,4,8,12,16 --out "results/${ARM}_poisson.json"
run arrivals    -n 20 --arrival stagger --rates 1,2,4,8,12,16 --out "results/${ARM}_stagger.json"
run arrivals    --arrival sync --burst 8,16,32,64          --out "results/${ARM}_sync.json"
run length      -n 20 -c 1                                 --out "results/${ARM}_length.json"
run language    -n 12 -c 1                                 --out "results/${ARM}_language.json"
echo; echo "=== $ARM COMPLETE ==="
