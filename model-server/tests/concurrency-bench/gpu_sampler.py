"""Sample one GPU's counters with nvidia-smi while a test cell runs.

Optional. Only meaningful when this script runs on the same host as the GPU
under test; pass --gpu-index to turn it on. Without it every cell reports
"NOT MEASURED" rather than guessing.

Read `utilization.gpu` with care: it is the share of time at least one kernel
was resident, not how much work the GPU did. It answers "was the GPU busy at
all", not "how busy". The counters that answer the second question need DCGM.
"""

from __future__ import annotations

import subprocess
import threading
import time

FIELDS = ["utilization.gpu", "utilization.memory", "memory.used",
          "clocks.sm", "power.draw", "temperature.gpu"]


class GpuSampler:
    """Background sampler. Use as a context manager around the work being measured."""

    def __init__(self, gpu_index: str | None, hz: float = 5.0):
        self.gpu_index = gpu_index
        self.interval = 1.0 / hz
        self.samples: list[dict] = []
        self._stop = threading.Event()
        self._t: threading.Thread | None = None

    def _run(self) -> None:
        # Always pinned with -i: on a multi-GPU host an unqualified query prints
        # one line per GPU and would silently report GPU 0.
        cmd = ["nvidia-smi", "-i", str(self.gpu_index), f"--query-gpu={','.join(FIELDS)}",
               "--format=csv,noheader,nounits"]
        while not self._stop.is_set():
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout
                parts = [p.strip() for p in out.strip().split(",")]
                rec: dict = {"t": round(time.monotonic(), 3)}
                for k, v in zip(FIELDS, parts, strict=False):
                    try:
                        rec[k] = float(v)
                    except ValueError:
                        rec[k] = None
                self.samples.append(rec)
            except Exception:                                    # noqa: BLE001, S110
                pass
            self._stop.wait(self.interval)

    def __enter__(self) -> GpuSampler:
        if self.gpu_index not in (None, ""):
            self._t = threading.Thread(target=self._run, daemon=True)
            self._t.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._t:
            self._t.join(3)

    def summary(self) -> dict:
        if not self.samples:
            return {"n_samples": 0, "note": "NOT MEASURED"}

        def stat(k: str) -> dict | None:
            xs = sorted(s[k] for s in self.samples if s.get(k) is not None)
            if not xs:
                return None
            return {"mean": round(sum(xs) / len(xs), 2), "p50": xs[len(xs) // 2],
                    "p95": xs[min(len(xs) - 1, int(0.95 * len(xs)))], "max": xs[-1]}

        return {"n_samples": len(self.samples), "gpu_index": self.gpu_index,
                **{k: stat(k) for k in FIELDS}}
