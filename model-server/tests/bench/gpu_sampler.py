#!/usr/bin/env python3
"""Sample GPU counters at 10 Hz around the work being measured.

Copied from stt/indic-transcribe/bench/gpu_sampler.py, which is generic and has
no STT in it. Copied rather than imported because the rest of that package hard-
codes container paths (`sys.path.insert(0, "/app/bench")`) and will not import
from here.

Read `utilization.gpu` with care: it is the fraction of time at least one kernel
was resident, not work done. A single small kernel occupying one SM reads 100%.
It is useful for "was the GPU busy at all" and useless for "how busy". The
counters that would answer that (SM_ACTIVE, PIPE_TENSOR_ACTIVE) need DCGM, which
is not installed here, and are reported as NOT MEASURED rather than guessed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time

FIELDS = [
    "utilization.gpu", "utilization.memory", "memory.used",
    "clocks.sm", "clocks.mem", "power.draw", "temperature.gpu",
]


class GpuSampler:
    """Background 10 Hz sampler. Use as a context manager around the work being measured."""

    def __init__(self, hz: float = 10.0):
        self.interval = 1.0 / hz
        self.samples: list[dict] = []
        self._stop = threading.Event()
        self._t: threading.Thread | None = None

    def _run(self):
        query = ",".join(FIELDS)
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    ["nvidia-smi", f"--query-gpu={query}",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=2,
                )
                parts = [p.strip() for p in out.stdout.strip().split(",")]
                rec = {"t": round(time.monotonic(), 3)}
                for k, v in zip(FIELDS, parts):
                    try:
                        rec[k] = float(v)
                    except ValueError:
                        rec[k] = None
                self.samples.append(rec)
            except Exception:
                pass
            self._stop.wait(self.interval)

    def __enter__(self):
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._t:
            self._t.join(3)

    def summary(self) -> dict:
        if not self.samples:
            return {"n_samples": 0, "note": "NOT MEASURED"}

        def stat(k):
            xs = [s[k] for s in self.samples if s.get(k) is not None]
            if not xs:
                return None
            xs.sort()
            return {
                "mean": round(sum(xs) / len(xs), 2),
                "p50": xs[len(xs) // 2],
                "p95": xs[min(len(xs) - 1, int(0.95 * len(xs)))],
                "max": xs[-1],
            }

        util = stat("utilization.gpu")
        return {
            "n_samples": len(self.samples),
            "hz": round(1.0 / self.interval, 1),
            **{k: stat(k) for k in FIELDS},
            # The counters that would actually settle the launch-bound question.
            "sm_active": "NOT MEASURED (needs DCGM; not installed)",
            "sm_occupancy": "NOT MEASURED (needs DCGM; not installed)",
            "dram_active": "NOT MEASURED (needs DCGM; not installed)",
            "pipe_tensor_active": "NOT MEASURED (needs DCGM; not installed)",
            "prediction_note": (
                "Prediction was: GPU-Util near 100% while SM occupancy is low and tensor pipes "
                "near idle, i.e. launch-bound. utilization.gpu alone CANNOT confirm this -- it "
                "measures kernel residency, not work. Treat a high value here as consistent "
                "with, not evidence for, the launch-bound hypothesis."
            ),
            "utilization_gpu_summary": util,
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--hz", type=float, default=10.0)
    ap.add_argument("--out")
    args = ap.parse_args()
    with GpuSampler(args.hz) as s:
        time.sleep(args.seconds)
    js = json.dumps(s.summary(), indent=2)
    print(js)
    if args.out:
        from pathlib import Path
        Path(args.out).write_text(js)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
