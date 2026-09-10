"""CallMetrics collection CRUD for per-call pipeline metrics."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.database import get_database
from app.services.call_log_service import get_call_log
from app.utils.mongo_utils import prepare_mongo_response

logger = logging.getLogger(__name__)

COLLECTION = "CallMetrics"


class CallMetricsNotFoundError(Exception):
    """Raised when metrics are missing for a call in the organisation."""

    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        super().__init__(f"Call metrics not found: {call_id}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_response(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    prepared = prepare_mongo_response(doc) or {}
    prepared.pop("_id", None)
    return prepared


def upsert_call_metrics(
    org_id: str,
    call_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Insert metrics for a call if none exist yet (write-once)."""
    get_call_log(org_id, call_id)

    existing = get_database()[COLLECTION].find_one(
        {"org_id": org_id, "call_id": call_id}
    )
    if existing:
        logger.debug("CallMetrics already set call_id=%s", call_id)
        return _to_response(existing) or {}

    doc = {
        "call_id": call_id,
        "org_id": org_id,
        "recorded_at": _now_iso(),
        "summary": payload.get("summary") or {},
        "transport": payload.get("transport"),
        "turns": payload.get("turns") or [],
        "latencies": payload.get("latencies") or {},
    }
    get_database()[COLLECTION].insert_one(doc)
    logger.info("CallMetrics created call_id=%s org=%s", call_id, org_id)
    return _to_response(doc) or {}


def _classify_processor(processor: str) -> str | None:
    """Fallback for older CallMetrics docs that lack ``stage``.

    Prefer ``entry["stage"]`` (stamped at write time from the pipeline role
    map). Name heuristics are brittle: ``OrpheusTTSService`` contains ``STT``.
    """
    base = (processor or "").split("#", 1)[0].upper()
    if base.endswith("TTSSERVICE") or base.endswith("TTS"):
        return "tts"
    if base.endswith("STTSERVICE") or base.endswith("STT"):
        return "stt"
    if base.endswith("LLMSERVICE") or base.endswith("LLM") or "LLM" in base:
        return "llm"
    return None


def _entry_stage(entry: dict[str, Any]) -> str | None:
    stage = entry.get("stage")
    if stage in ("stt", "llm", "tts"):
        return stage
    return _classify_processor(entry.get("processor", ""))


def _stage_secs_from_breakdown(breakdown: dict[str, Any], kind: str) -> float | None:
    for entry in breakdown.get("ttfb") or []:
        if _entry_stage(entry) == kind:
            duration = entry.get("duration_secs")
            return float(duration) if duration is not None else None
    return None


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _with_avg_latency(doc: dict[str, Any]) -> dict[str, Any]:
    """Adds avg_stt_secs/avg_tts_secs/avg_llm_secs/avg_latency_secs to
    ``summary``, computed from the per-turn ttfb breakdowns (mirrors the
    frontend's normalizeCallMetrics so both surfaces agree) — bot-initiated
    turns with no real user turn are excluded, same as there. avg_latency_secs
    is the sum of whichever per-stage averages are actually available, since a
    call missing one stage's data shouldn't make the whole figure disappear."""
    breakdowns = (doc.get("latencies") or {}).get("breakdowns") or []
    stt_values: list[float] = []
    tts_values: list[float] = []
    llm_values: list[float] = []
    for breakdown in breakdowns:
        if breakdown.get("user_turn_start_time") is None:
            continue
        stt = _stage_secs_from_breakdown(breakdown, "stt")
        tts = _stage_secs_from_breakdown(breakdown, "tts")
        llm = _stage_secs_from_breakdown(breakdown, "llm")
        if stt is not None:
            stt_values.append(stt)
        if tts is not None:
            tts_values.append(tts)
        if llm is not None:
            llm_values.append(llm)

    avg_stt = _average(stt_values)
    avg_tts = _average(tts_values)
    avg_llm = _average(llm_values)
    available = [v for v in (avg_stt, avg_tts, avg_llm) if v is not None]

    summary = dict(doc.get("summary") or {})
    summary["avg_stt_secs"] = avg_stt
    summary["avg_tts_secs"] = avg_tts
    summary["avg_llm_secs"] = avg_llm
    summary["avg_latency_secs"] = sum(available) if available else None
    doc["summary"] = summary
    return doc


def get_call_metrics(org_id: str, call_id: str) -> dict[str, Any]:
    """Fetch metrics for one call scoped to ``org_id``."""
    get_call_log(org_id, call_id)

    doc = get_database()[COLLECTION].find_one({"org_id": org_id, "call_id": call_id})
    if not doc:
        raise CallMetricsNotFoundError(call_id)
    return _with_avg_latency(_to_response(doc) or {})
