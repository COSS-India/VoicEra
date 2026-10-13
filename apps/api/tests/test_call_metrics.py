"""Call metrics GET/PUT endpoint tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from test_call_artifacts import (
    _CALL_STORE,
    _FakeCollection,
    _make_client,
    _sample_call_doc,
)

_METRICS_STORE: dict[str, dict[str, Any]] = {}


class _MetricsFakeCollection(_FakeCollection):
    def insert_one(self, doc: dict[str, Any]) -> MagicMock:
        self._store[doc["call_id"]] = dict(doc)
        result = MagicMock()
        result.inserted_id = doc["call_id"]
        return result


def _fake_db() -> dict[str, Any]:
    return {
        "CallLogs": _FakeCollection(_CALL_STORE),
        "CallMetrics": _MetricsFakeCollection(_METRICS_STORE),
    }


def _patch_metrics_db(target: str):
    return patch(target, side_effect=_fake_db)


def _sample_metrics_doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "call_id": "call-abc-123",
        "org_id": "org-1",
        "recorded_at": "2026-01-01T00:05:00+00:00",
        "summary": {"turn_count": 2, "interrupted_turn_count": 0},
        "transport": {"client_connected_secs": 0.4},
        "turns": [{"turn_number": 1, "duration_secs": 10.0, "was_interrupted": False}],
        "latencies": {"user_to_bot_secs": [0.9, 1.1]},
    }
    doc.update(overrides)
    return doc


@_patch_metrics_db("app.services.call_metrics_service.get_database")
@_patch_metrics_db("app.services.call_log_service.get_database")
def test_put_call_metrics_creates_doc(
    _call_log_db: MagicMock,
    _metrics_db: MagicMock,
) -> None:
    _CALL_STORE.clear()
    _METRICS_STORE.clear()
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    client = _make_client()
    body = {
        "summary": {"turn_count": 1},
        "transport": None,
        "turns": [],
        "latencies": {"user_to_bot_secs": [0.8]},
    }

    response = client.put("/api/v1/calls/call-abc-123/metrics", json=body)

    assert response.status_code == 200
    stored = _METRICS_STORE["call-abc-123"]
    assert stored["summary"]["turn_count"] == 1
    assert stored["latencies"]["user_to_bot_secs"] == [0.8]
    assert "metrics" not in _CALL_STORE["call-abc-123"]


@_patch_metrics_db("app.services.call_metrics_service.get_database")
@_patch_metrics_db("app.services.call_log_service.get_database")
def test_get_call_metrics_returns_doc(
    _call_log_db: MagicMock,
    _metrics_db: MagicMock,
) -> None:
    _CALL_STORE.clear()
    _METRICS_STORE.clear()
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    _METRICS_STORE["call-abc-123"] = _sample_metrics_doc()
    client = _make_client()

    response = client.get("/api/v1/calls/call-abc-123/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["turn_count"] == 2
    assert body["latencies"]["user_to_bot_secs"] == [0.9, 1.1]


@_patch_metrics_db("app.services.call_metrics_service.get_database")
@_patch_metrics_db("app.services.call_log_service.get_database")
def test_get_call_does_not_include_metrics(
    _call_log_db: MagicMock,
    _metrics_db: MagicMock,
) -> None:
    _CALL_STORE.clear()
    _METRICS_STORE.clear()
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    _METRICS_STORE["call-abc-123"] = _sample_metrics_doc()
    client = _make_client()

    response = client.get("/api/v1/calls/call-abc-123")

    assert response.status_code == 200
    assert "metrics" not in response.json()


@_patch_metrics_db("app.services.call_metrics_service.get_database")
@_patch_metrics_db("app.services.call_log_service.get_database")
def test_put_call_metrics_write_once(
    _call_log_db: MagicMock,
    _metrics_db: MagicMock,
) -> None:
    _CALL_STORE.clear()
    _METRICS_STORE.clear()
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    _METRICS_STORE["call-abc-123"] = _sample_metrics_doc()
    client = _make_client()
    replacement = {
        "summary": {"turn_count": 99},
        "turns": [],
        "latencies": {},
    }

    response = client.put("/api/v1/calls/call-abc-123/metrics", json=replacement)

    assert response.status_code == 200
    assert _METRICS_STORE["call-abc-123"]["summary"]["turn_count"] == 2


@_patch_metrics_db("app.services.call_metrics_service.get_database")
@_patch_metrics_db("app.services.call_log_service.get_database")
def test_put_call_metrics_backfills_empty_placeholder(
    _call_log_db: MagicMock,
    _metrics_db: MagicMock,
) -> None:
    """A reconnect can leave a placeholder doc from a run that dropped before
    the caller was answered. It still has turns (the runtime opens turn 1 on
    StartFrame) and maybe a greeting breakdown, but no user→bot latency. The
    real metrics from the run that actually finished the call must still
    land, not be silently discarded by write-once — see upsert_call_metrics."""
    _CALL_STORE.clear()
    _METRICS_STORE.clear()
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    _METRICS_STORE["call-abc-123"] = _sample_metrics_doc(
        summary={"turn_count": 1, "interrupted_turn_count": 1},
        turns=[
            {"turn_number": 1, "started": True},
            {"turn_number": 1, "duration_secs": 4.2, "was_interrupted": True},
        ],
        latencies={
            "first_bot_speech_secs": 0.3,
            "user_to_bot_secs": [],
            "breakdowns": [
                {
                    "ttfb": [{"processor": "RayaTTSService#1", "duration_secs": 0.2}],
                    "user_turn_start_time": None,
                    "turn_number": 1,
                }
            ],
        },
    )
    client = _make_client()
    real_metrics = {
        "summary": {"turn_count": 2},
        "turns": [{"turn_number": 1, "duration_secs": 9.0, "was_interrupted": False}],
        "latencies": {
            "user_to_bot_secs": [1.4],
            "breakdowns": [
                {
                    "ttfb": [
                        {"processor": "RayaSTTService#1", "duration_secs": 0.6},
                        {"processor": "BlueDotsLLMService#1", "duration_secs": 1.1},
                        {"processor": "RayaTTSService#1", "duration_secs": 0.3},
                    ],
                    "user_turn_start_time": 1.0,
                }
            ]
        },
    }

    response = client.put("/api/v1/calls/call-abc-123/metrics", json=real_metrics)

    assert response.status_code == 200
    stored = _METRICS_STORE["call-abc-123"]
    assert stored["summary"]["turn_count"] == 2
    assert stored["latencies"]["breakdowns"][0]["ttfb"][0]["duration_secs"] == 0.6

    # And it's locked in from here — a THIRD write does not clobber it.
    response2 = client.put(
        "/api/v1/calls/call-abc-123/metrics",
        json={"summary": {"turn_count": 99}, "turns": [], "latencies": {}},
    )
    assert response2.status_code == 200
    assert _METRICS_STORE["call-abc-123"]["summary"]["turn_count"] == 2


@_patch_metrics_db("app.services.call_metrics_service.get_database")
@_patch_metrics_db("app.services.call_log_service.get_database")
def test_put_call_metrics_keeps_richer_stored_doc(
    _call_log_db: MagicMock,
    _metrics_db: MagicMock,
) -> None:
    """A later run with fewer answered user turns must not replace the run
    that carried more of the conversation."""
    _CALL_STORE.clear()
    _METRICS_STORE.clear()
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    _METRICS_STORE["call-abc-123"] = _sample_metrics_doc()  # 2 answered turns
    client = _make_client()
    poorer = {
        "summary": {"turn_count": 99},
        "turns": [{"turn_number": 1, "duration_secs": 3.0, "was_interrupted": False}],
        "latencies": {"user_to_bot_secs": [0.8]},
    }

    response = client.put("/api/v1/calls/call-abc-123/metrics", json=poorer)

    assert response.status_code == 200
    assert _METRICS_STORE["call-abc-123"]["summary"]["turn_count"] == 2


@_patch_metrics_db("app.services.call_metrics_service.get_database")
@_patch_metrics_db("app.services.call_log_service.get_database")
def test_get_call_metrics_not_found(
    _call_log_db: MagicMock,
    _metrics_db: MagicMock,
) -> None:
    _CALL_STORE.clear()
    _METRICS_STORE.clear()
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    client = _make_client()

    response = client.get("/api/v1/calls/call-abc-123/metrics")

    assert response.status_code == 404


def test_classify_processor_orpheus_tts_not_stt() -> None:
    from app.services.call_metrics_service import _classify_processor, _entry_stage

    assert _classify_processor("BhashiniOrpheusTTSService#2") == "tts"
    assert _classify_processor("BhashiniNemotronSTTService#2") == "stt"
    assert _classify_processor("OpenAILLMService#4") == "llm"
    # Explicit stage wins even if the processor name would confuse heuristics.
    assert (
        _entry_stage({"processor": "WeirdName#0", "stage": "tts", "duration_secs": 0.1})
        == "tts"
    )


@_patch_metrics_db("app.services.call_metrics_service.get_database")
@_patch_metrics_db("app.services.call_log_service.get_database")
def test_get_call_metrics_avg_tts_with_orpheus(
    _call_log_db: MagicMock,
    _metrics_db: MagicMock,
) -> None:
    _CALL_STORE.clear()
    _METRICS_STORE.clear()
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    _METRICS_STORE["call-abc-123"] = _sample_metrics_doc(
        latencies={
            "user_to_bot_secs": [1.0],
            "breakdowns": [
                {
                    "ttfb": [
                        {
                            "processor": "BhashiniNemotronSTTService#2",
                            "duration_secs": 0.5,
                        },
                        {
                            "processor": "OpenAILLMService#4",
                            "duration_secs": 0.9,
                        },
                        {
                            "processor": "BhashiniOrpheusTTSService#2",
                            "duration_secs": 0.4,
                        },
                    ],
                    "user_turn_start_time": 1.0,
                }
            ],
        }
    )
    client = _make_client()

    response = client.get("/api/v1/calls/call-abc-123/metrics")

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["avg_stt_secs"] == 0.5
    assert summary["avg_llm_secs"] == 0.9
    assert summary["avg_tts_secs"] == 0.4
    assert summary["avg_latency_secs"] == 1.3  # LLM + TTS only (STT excluded)


@_patch_metrics_db("app.services.call_metrics_service.get_database")
@_patch_metrics_db("app.services.call_log_service.get_database")
def test_get_call_metrics_prefers_explicit_stage(
    _call_log_db: MagicMock,
    _metrics_db: MagicMock,
) -> None:
    _CALL_STORE.clear()
    _METRICS_STORE.clear()
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    _METRICS_STORE["call-abc-123"] = _sample_metrics_doc(
        latencies={
            "breakdowns": [
                {
                    "ttfb": [
                        {
                            "processor": "CustomVendorService#1",
                            "stage": "tts",
                            "duration_secs": 0.33,
                        }
                    ],
                    "user_turn_start_time": 1.0,
                }
            ],
        }
    )
    client = _make_client()

    response = client.get("/api/v1/calls/call-abc-123/metrics")

    assert response.status_code == 200
    assert response.json()["summary"]["avg_tts_secs"] == 0.33


@_patch_metrics_db("app.services.call_metrics_service.get_database")
@_patch_metrics_db("app.services.call_log_service.get_database")
def test_get_call_metrics_averages_first_breakdown_per_turn(
    _call_log_db: MagicMock,
    _metrics_db: MagicMock,
) -> None:
    """Mirrors the frontend's normalizeCallMetrics: a stray second breakdown
    in the same turn (e.g. the bot resuming after a sub-threshold
    backchannel) must not skew the averages. Legacy breakdowns without
    turn_number still all count."""

    def tts_breakdown(secs: float, turn_number: int | None = None) -> dict[str, Any]:
        breakdown: dict[str, Any] = {
            "ttfb": [{"processor": "X#1", "stage": "tts", "duration_secs": secs}],
            "user_turn_start_time": 1.0,
        }
        if turn_number is not None:
            breakdown["turn_number"] = turn_number
        return breakdown

    _CALL_STORE.clear()
    _METRICS_STORE.clear()
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    _METRICS_STORE["call-abc-123"] = _sample_metrics_doc(
        latencies={
            "breakdowns": [
                tts_breakdown(0.2, 2),
                tts_breakdown(0.9, 2),
                tts_breakdown(0.4, 3),
            ]
        }
    )
    client = _make_client()

    response = client.get("/api/v1/calls/call-abc-123/metrics")

    assert response.status_code == 200
    assert response.json()["summary"]["avg_tts_secs"] == pytest.approx(0.3)

    _METRICS_STORE["call-abc-123"] = _sample_metrics_doc(
        latencies={"breakdowns": [tts_breakdown(0.2), tts_breakdown(0.4)]}
    )
    response = client.get("/api/v1/calls/call-abc-123/metrics")
    assert response.json()["summary"]["avg_tts_secs"] == pytest.approx(0.3)


@_patch_metrics_db("app.services.call_metrics_service.get_database")
@_patch_metrics_db("app.services.call_log_service.get_database")
def test_put_call_metrics_tolerates_malformed_user_to_bot_secs(
    _call_log_db: MagicMock,
    _metrics_db: MagicMock,
) -> None:
    _CALL_STORE.clear()
    _METRICS_STORE.clear()
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    _METRICS_STORE["call-abc-123"] = _sample_metrics_doc()
    client = _make_client()

    response = client.put(
        "/api/v1/calls/call-abc-123/metrics",
        json={"summary": {"turn_count": 99}, "latencies": {"user_to_bot_secs": 7}},
    )

    assert response.status_code == 200
    assert _METRICS_STORE["call-abc-123"]["summary"]["turn_count"] == 2
