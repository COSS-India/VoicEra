"""Shared pieces of the concurrency bench: statistics, arrival schedules, the
warm-up plan, run metadata and per-request records.

Nothing in here knows which model is under test.
"""

from __future__ import annotations

import asyncio
import json
import platform
import random
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- output
def say(*parts: object) -> None:
    """Print and flush at once, so progress shows live under tee, nohup or tmux."""
    print(*parts, flush=True)


def warn(*parts: object) -> None:
    print("WARNING:", *parts, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- statistics
def pct(xs: list[float], q: float) -> float | None:
    """Nearest-rank percentile, no interpolation."""
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 4)


def stats(xs: list[float | None]) -> dict:
    vals = [x for x in xs if x is not None]
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "mean": round(sum(vals) / len(vals), 4),
            "p50": pct(vals, .50), "p95": pct(vals, .95), "p99": pct(vals, .99),
            "min": round(min(vals), 4), "max": round(max(vals), 4)}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k/n."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def parse_levels(s: str) -> list[int]:
    return [int(x) for x in s.split(",") if x.strip()]


# --------------------------------------------------------------------------- schedules
def batch_starts(n: int, mode: str, t0: float, window_s: float,
                 rng: random.Random) -> list[float]:
    """When each of the N requests in one round is due to start.

    sync    all N at t0 -- Test A, a single batch.
    random  N start times drawn uniformly at random in [t0, t0 + window_s) --
            Test B. This is exactly what a Poisson arrival process looks like
            once you condition on N arrivals in the window. The caller keeps one
            rng per N, so every round gets a fresh draw.
    """
    if mode == "sync":
        return [t0] * n
    if mode == "random":
        return sorted(t0 + rng.uniform(0.0, window_s) for _ in range(n))
    raise ValueError(f"unknown mode {mode!r}")


async def sleep_until(t: float) -> None:
    d = t - time.monotonic()
    if d > 0:
        await asyncio.sleep(d)


# --------------------------------------------------------------------------- client health
class LoopLag:
    """Measures how late this process's event loop wakes up.

    If the load generator itself falls behind, the numbers describe the client,
    not the server. A cell whose p95 lag exceeds 50 ms is flagged client-bound.
    """

    THRESHOLD_MS = 50.0

    def __init__(self, every: float = 0.05):
        self.every, self.lag, self.task = every, [], None

    async def _run(self) -> None:
        while True:
            t = time.monotonic()
            await asyncio.sleep(self.every)
            self.lag.append((time.monotonic() - t - self.every) * 1000)

    def __enter__(self) -> LoopLag:
        self.task = asyncio.ensure_future(self._run())
        return self

    def __exit__(self, *exc: object) -> None:
        if self.task:
            self.task.cancel()

    def summary(self) -> dict:
        s = stats(self.lag)
        s["client_bound_suspected"] = bool((s.get("p95") or 0) > self.THRESHOLD_MS)
        return s


# --------------------------------------------------------------------------- warm-up
async def warm_up(single: Callable[[], Awaitable[object]],
                  batch: Callable[[int], Awaitable[object]],
                  singles: int, batches: list[int], budget_s: float) -> dict:
    """Run warm-up traffic and throw the results away.

    `singles` one-at-a-time requests, then one batch of each size in `batches`.
    The whole warm-up gets `budget_s` seconds. A batch still running when the
    budget runs out is cancelled with a warning and the test proceeds; batches
    not yet started are skipped.
    """
    t0 = time.monotonic()
    log = {"singles": singles, "batches": batches, "budget_s": budget_s, "steps": []}
    for i in range(singles):
        t = time.monotonic()
        await single()
        log["steps"].append({"step": f"single {i + 1}", "s": round(time.monotonic() - t, 2)})
    say(f"  warm-up: {singles} single requests done")
    for b in batches:
        left = budget_s - (time.monotonic() - t0)
        if left <= 0:
            warn(f"warm-up budget ({budget_s:.0f} s) used up; skipping batch of {b}")
            log["steps"].append({"step": f"batch {b}", "skipped": "budget"})
            continue
        t = time.monotonic()
        try:
            await asyncio.wait_for(batch(b), left)
            log["steps"].append({"step": f"batch {b}", "s": round(time.monotonic() - t, 2)})
            say(f"  warm-up: batch of {b} done in {time.monotonic() - t:.1f} s")
        except (asyncio.TimeoutError, TimeoutError):  # noqa: UP041 -- distinct on Python 3.10
            warn(f"warm-up batch of {b} cut off at the {budget_s:.0f} s budget")
            log["steps"].append({"step": f"batch {b}", "cut_off_s": round(left, 1)})
    log["total_s"] = round(time.monotonic() - t0, 1)
    return log


# --------------------------------------------------------------------------- run records
def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:                                            # noqa: BLE001
        return None


def gpu_inventory(gpu_index: str | None) -> str:
    """nvidia-smi description of the GPU under test, if this host has one."""
    if gpu_index in (None, ""):
        return "NOT MEASURED (no --gpu-index; client may be on another host)"
    cmd = ["nvidia-smi", "-i", str(gpu_index),
           "--query-gpu=index,name,memory.total,memory.used,driver_version,compute_mode",
           "--format=csv,noheader"]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip() \
            or "NOT MEASURED"
    except Exception:                                            # noqa: BLE001
        return "NOT MEASURED (nvidia-smi unavailable)"


def run_meta(args: object, health: dict, extra: dict | None = None) -> dict:
    return {
        "when_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "client_host": platform.node(),
        "python": platform.python_version(),
        "git_commit": git_commit(),
        "gpu": gpu_inventory(getattr(args, "gpu_index", None)),
        "server_notes": getattr(args, "note", None) or [],
        "health_at_start": health,
        "settings": {k: v for k, v in vars(args).items() if not k.startswith("_")},
        **(extra or {}),
    }


class RequestLog:
    """One JSON line per request, appended as each cell finishes.

    Kept so questions nobody thought to ask up front (a runaway rate, a slow
    clip, a single bad round) can be answered later without a rerun.
    """

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")

    def write(self, rows: list[dict]) -> None:
        with self.path.open("a") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
