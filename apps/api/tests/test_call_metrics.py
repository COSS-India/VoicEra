"""Call metrics GET/PUT endpoint tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

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
