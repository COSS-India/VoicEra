"""GPU SLA collector via nvidia-smi, with persisted sample history."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from datetime import timedelta
from typing import Any

from app.services.sla import targets
from app.services.sla.gpu.store import (
    aggregate_gpu_history,
    begin_restart_event,
    latest_ready_restart,
    mark_restart_ready,
    open_restart,
    record_sample,
)
from app.services.sla.metrics import metric, no_data_metric
from app.services.sla.status_rules import threshold_operating

logger = logging.getLogger(__name__)

_QUERY_FIELDS = [
    "index",
    "uuid",
    "name",
    "memory.used",
    "memory.total",
    "utilization.gpu",
    "utilization.memory",
    "temperature.gpu",
    "power.draw",
]

_SAMPLER_TASK: asyncio.Task[None] | None = None
_CURRENT_RESTART_ID: str | None = None
SAMPLE_INTERVAL_SECS = 5.0


def _parse_float(value: str) -> float | None:
    text = (value or "").strip()
    if not text or text.upper() in {"N/A", "[N/A]", "NOT SUPPORTED"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def run_nvidia_smi() -> dict[str, Any]:
    """Query every visible GPU. Never invents numbers."""
    if shutil.which("nvidia-smi") is None:
        return {
            "available": False,
            "failed": False,
            "reason": "nvidia-smi not on PATH",
            "gpus": [],
        }
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={','.join(_QUERY_FIELDS)}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("nvidia-smi failed: %s", exc)
        return {
            "available": True,
            "failed": True,
            "reason": str(exc),
            "gpus": [],
        }
    if result.returncode != 0:
        reason = (result.stderr or result.stdout or "nvidia-smi exited non-zero").strip()
        return {
            "available": True,
            "failed": True,
            "reason": reason,
            "gpus": [],
        }

    gpus: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < len(_QUERY_FIELDS):
            continue
        values = dict(zip(_QUERY_FIELDS, parts))
        gpus.append(
            {
                "index": int(_parse_float(values["index"]) or 0),
                "uuid": values["uuid"],
                "name": values["name"],
                "memory_used_mib": _parse_float(values["memory.used"]),
                "memory_total_mib": _parse_float(values["memory.total"]),
                "utilization_gpu_pct": _parse_float(values["utilization.gpu"]),
                "utilization_memory_pct": _parse_float(values["utilization.memory"]),
                "temperature_c": _parse_float(values["temperature.gpu"]),
                "power_draw_w": _parse_float(values["power.draw"]),
            }
        )
    return {
        "available": True,
        "failed": False,
        "reason": None,
        "gpus": gpus,
    }


def _sample_is_healthy(sample: dict[str, Any]) -> bool:
    return bool(
        sample.get("available")
        and not sample.get("failed")
        and len(sample.get("gpus") or []) > 0
    )


def _max_util(gpus: list[dict[str, Any]]) -> float | None:
    utils = [
        g["utilization_gpu_pct"]
        for g in gpus
        if g.get("utilization_gpu_pct") is not None
    ]
    return max(utils) if utils else None


def sample_and_store() -> dict[str, Any]:
    """Run nvidia-smi once and append to GpuTelemetrySamples."""
    sample = run_nvidia_smi()
    healthy = _sample_is_healthy(sample)
    peak = _max_util(sample.get("gpus") or [])
    try:
        stored = record_sample(
            healthy=healthy,
            max_utilization_pct=peak,
            gpu_count=len(sample.get("gpus") or []),
            reason=sample.get("reason"),
            raw={"gpus": sample.get("gpus") or []},
        )
    except Exception as exc:
        logger.warning("Failed to persist GPU sample: %s", exc)
        stored = None

    global _CURRENT_RESTART_ID
    if healthy and _CURRENT_RESTART_ID:
        try:
            mark_restart_ready(_CURRENT_RESTART_ID)
            _CURRENT_RESTART_ID = None
        except Exception as exc:
            logger.warning("Failed to mark GPU restart ready: %s", exc)
    elif healthy:
        open_doc = None
        try:
            open_doc = open_restart()
        except Exception:
            open_doc = None
        if open_doc and open_doc.get("restart_id"):
            try:
                mark_restart_ready(str(open_doc["restart_id"]))
            except Exception as exc:
                logger.warning("Failed to close open GPU restart: %s", exc)

    return {"live": sample, "stored": stored, "healthy": healthy, "peak": peak}


def collect_gpu() -> dict[str, Any]:
    """Sample now, store, and return agreed-target vs actual GPU SLA rows."""
    snap = sample_and_store()
    sample = snap["live"]
    gpus = sample.get("gpus") or []
    peak_live = snap["peak"]
    history = aggregate_gpu_history(
        window=timedelta(days=1),
        peak_threshold=targets.GPU_BUSY_ALERT_PCT,
    )
    restart = latest_ready_restart()
    ready_secs = None
    if restart and restart.get("ready_secs") is not None:
        ready_secs = float(restart["ready_secs"])
        # Report in minutes to match SLA target unit.
        ready_mins = round(ready_secs / 60.0, 2)
    else:
        ready_mins = None

    source = (
        "nvidia-smi"
        if sample.get("available") and not sample.get("failed")
        else "unavailable"
    )
    hist_source = "gpu_telemetry_samples" if history["sample_count"] else "no_history"

    health_actual = history["health_check_success_pct"]
    uptime_actual = history["healthy_gpu_uptime_pct"]
    peak_actual = history["peak_utilization_pct"]
    if peak_actual is None:
        peak_actual = peak_live

    metrics = [
        metric(
            key="health_check_success",
            label="Health check success",
            target=targets.HEALTH_CHECK_SUCCESS_PCT,
            comparator="gte",
            unit="pct",
            actual=health_actual,
            source=hist_source,
            scope="deployment",
            sample_count=history["sample_count"],
            operating_status=threshold_operating(
                health_actual,
                target=targets.HEALTH_CHECK_SUCCESS_PCT,
                comparator="gte",
            ),
        ),
        metric(
            key="healthy_gpu_uptime",
            label="Healthy GPU uptime",
            target=targets.HEALTHY_GPU_UPTIME_PCT,
            comparator="gte",
            unit="pct",
            actual=uptime_actual,
            source=hist_source,
            scope="deployment",
            sample_count=history["sample_count"],
            operating_status=threshold_operating(
                uptime_actual,
                target=targets.HEALTHY_GPU_UPTIME_PCT,
                comparator="gte",
            ),
        ),
        metric(
            key="peak_gpu_load",
            label="Peak GPU load",
            target=targets.GPU_BUSY_ALERT_PCT,
            comparator="lte",
            unit="pct",
            actual=peak_actual,
            source=source if peak_actual is not None else hist_source,
            scope="deployment",
            operating_status=threshold_operating(
                peak_actual,
                target=targets.GPU_BUSY_ALERT_PCT,
                comparator="lte",
            ),
        ),
        metric(
            key="peak_gpu_load_duration",
            label=(
                f"Time at or above peak GPU load "
                f"({targets.GPU_BUSY_ALERT_PCT:g}%)"
            ),
            target=0.0,
            comparator="lte",
            unit="s",
            actual=history["peak_above_threshold_seconds"],
            source=hist_source,
            scope="deployment",
            sample_count=history["sample_count"],
        ),
        metric(
            key="model_ready_after_restart",
            label="Model ready after restart",
            target=targets.MODEL_READY_AFTER_RESTART_MIN,
            comparator="lte",
            unit="min",
            actual=ready_mins,
            source="gpu_restart_events" if ready_mins is not None else "no_restart_history",
            scope="deployment",
            operating_status=threshold_operating(
                ready_mins,
                target=targets.MODEL_READY_AFTER_RESTART_MIN,
                comparator="lte",
            ),
        ),
        no_data_metric(
            key="spare_gpu_takeover",
            label="Spare GPU takes over",
            target=targets.GPU_FAILOVER_TAKEOVER_MIN,
            comparator="lte",
            unit="min",
            source="no_failover_path",
            scope="deployment",
        ),
    ]

    return {
        "scope": "deployment",
        "source": source,
        "reason": sample.get("reason"),
        "sample_interval_secs": SAMPLE_INTERVAL_SECS,
        "gpus": gpus,
        "history": history,
        "metrics": metrics,
    }


def note_process_start() -> str | None:
    """Call from API lifespan when the process boots."""
    global _CURRENT_RESTART_ID
    try:
        _CURRENT_RESTART_ID = begin_restart_event()
        return _CURRENT_RESTART_ID
    except Exception as exc:
        logger.warning("Could not record GPU restart start: %s", exc)
        _CURRENT_RESTART_ID = None
        return None


async def _sampler_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(sample_and_store)
        except Exception as exc:
            logger.warning("GPU sampler tick failed: %s", exc)
        await asyncio.sleep(SAMPLE_INTERVAL_SECS)


def start_gpu_sampler() -> None:
    """Background 5s nvidia-smi sampler. No-op if already running."""
    global _SAMPLER_TASK
    if _SAMPLER_TASK is not None and not _SAMPLER_TASK.done():
        return
    note_process_start()
    _SAMPLER_TASK = asyncio.create_task(_sampler_loop(), name="sla-gpu-sampler")
    logger.info("SLA GPU sampler started (every %ss)", SAMPLE_INTERVAL_SECS)


async def stop_gpu_sampler() -> None:
    global _SAMPLER_TASK
    task = _SAMPLER_TASK
    _SAMPLER_TASK = None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
