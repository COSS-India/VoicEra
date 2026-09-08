"""Call artifact PATCH and MinIO proxy route tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import calls
from app.storage.minio_client import MinIOStorage

_CALL_STORE: dict[str, dict[str, Any]] = {}


class _FakeCollection:
    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self._store = store

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self._store.values():
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> MagicMock:
        doc = self.find_one(query)
        result = MagicMock()
        if not doc:
            result.matched_count = 0
            result.modified_count = 0
            return result
        key = doc["call_id"]
        updated = dict(doc)
        if "$set" in update:
            updated.update(update["$set"])
        self._store[key] = updated
        result.matched_count = 1
        result.modified_count = 1
        return result


def _fake_db() -> dict[str, Any]:
    return {"CallLogs": _FakeCollection(_CALL_STORE)}


def _patch_db(target: str):
    return patch(target, side_effect=_fake_db)


def _admin_user() -> dict[str, Any]:
    return {"email": "admin@example.com", "org_id": "org-1", "role": "admin"}


def _other_org_admin() -> dict[str, Any]:
    return {"email": "other@example.com", "org_id": "org-2", "role": "admin"}


def _make_client(user_fn=_admin_user) -> TestClient:
    app = FastAPI()
    app.include_router(calls.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = user_fn
    return TestClient(app)


def _sample_call_doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "call_id": "call-abc-123",
        "org_id": "org-1",
        "agent_id": "agent-1",
        "call_type": "outbound",
        "status": "ringing",
        "from_number": "+15559876543",
        "to_number": "+14155551234",
        "start_time_utc": "2026-01-01T00:00:00+00:00",
        "end_time_utc": None,
        "duration": None,
        "recording_url": None,
        "transcript_url": None,
    }
    doc.update(overrides)
    return doc


@pytest.fixture(autouse=True)
def clear_store() -> None:
    _CALL_STORE.clear()


@_patch_db("app.services.call_log_service.get_database")
def test_patch_call_sets_minio_urls(_calls_db: MagicMock) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    client = _make_client()

    response = client.patch(
        "/api/v1/calls/call-abc-123",
        json={
            "transcript_url": "minio://voicera-calls/org-1/call-abc-123/transcript.txt",
            "recording_url": "minio://voicera-calls/org-1/call-abc-123/recording.wav",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transcript_url"] == "/api/v1/calls/call-abc-123/transcript"
    assert body["recording_url"] == "/api/v1/calls/call-abc-123/recording"
    stored = _CALL_STORE["call-abc-123"]
    assert stored["transcript_url"].startswith("minio://")
    assert stored["recording_url"].startswith("minio://")


@_patch_db("app.services.call_log_service.get_database")
def test_patch_call_rejects_empty_body(_calls_db: MagicMock) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    client = _make_client()
    response = client.patch("/api/v1/calls/call-abc-123", json={})
    assert response.status_code == 400


@_patch_db("app.services.call_log_service.get_database")
def test_patch_call_sets_completion_fields(_calls_db: MagicMock) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc(
        status="in_progress",
        call_response="pending",
    )
    client = _make_client()

    response = client.patch(
        "/api/v1/calls/call-abc-123",
        json={
            "end_time_utc": "2026-01-01T00:01:00+00:00",
            "status": "completed",
            "call_response": "answered",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["call_response"] == "answered"
    assert body["duration"] == 60.0


@_patch_db("app.services.call_log_service.get_database")
def test_patch_call_does_not_overwrite_answered(_calls_db: MagicMock) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc(
        status="completed",
        call_response="answered",
        end_time_utc="2026-01-01T00:01:00+00:00",
        duration=60.0,
    )
    client = _make_client()

    response = client.patch(
        "/api/v1/calls/call-abc-123",
        json={
            "status": "completed",
            "call_response": "no_answer",
            "end_time_utc": "2026-01-01T00:05:00+00:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["call_response"] == "answered"
    assert body["end_time_utc"] == "2026-01-01T00:01:00+00:00"


@_patch_db("app.services.call_log_service.get_database")
def test_patch_call_by_provider_sid(_calls_db: MagicMock) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc(
        provider_call_sid="vobiz-uuid-1",
        status="in_progress",
        call_response="pending",
    )
    client = _make_client()

    response = client.patch(
        "/api/v1/calls/by-provider-sid/vobiz-uuid-1",
        json={
            "status": "completed",
            "call_response": "busy",
            "end_time_utc": "2026-01-01T00:01:00+00:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["call_response"] == "busy"
    assert body["status"] == "completed"


@_patch_db("app.services.call_log_service.get_database")
def test_patch_call_end_time_idempotent(_calls_db: MagicMock) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    client = _make_client()

    first = client.patch(
        "/api/v1/calls/call-abc-123",
        json={"end_time_utc": "2026-01-01T00:01:00+00:00"},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["end_time_utc"] == "2026-01-01T00:01:00+00:00"
    assert body["duration"] == 60.0

    second = client.patch(
        "/api/v1/calls/call-abc-123",
        json={"end_time_utc": "2026-01-01T00:05:00+00:00"},
    )
    assert second.status_code == 200
    unchanged = second.json()
    assert unchanged["end_time_utc"] == "2026-01-01T00:01:00+00:00"
    assert unchanged["duration"] == 60.0


@_patch_db("app.services.call_log_service.get_database")
def test_patch_call_org_isolation(_calls_db: MagicMock) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc(org_id="org-1")
    client = _make_client(_other_org_admin)
    response = client.patch(
        "/api/v1/calls/call-abc-123",
        json={"transcript_url": "minio://voicera-calls/org-1/call-abc-123/transcript.txt"},
    )
    assert response.status_code == 404


@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.MinIOStorage")
def test_get_call_recording_proxies_minio(
    storage_cls: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc(
        recording_url="minio://voicera-calls/org-1/call-abc-123/recording.wav",
    )
    storage = storage_cls.return_value
    storage.object_exists.return_value = True
    storage_cls.parse_minio_url = MinIOStorage.parse_minio_url

    response_obj = MagicMock()
    response_obj.stream.return_value = [b"RIFF", b"WAVE"]
    storage.client.get_object.return_value = response_obj

    client = _make_client()
    response = client.get("/api/v1/calls/call-abc-123/recording")

    assert response.status_code == 200
    assert response.content == b"RIFFWAVE"
    storage.object_exists.assert_called_once_with(
        "voicera-calls",
        "org-1/call-abc-123/recording.wav",
    )


@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.MinIOStorage")
def test_get_call_recording_missing_object(
    storage_cls: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc(
        recording_url="minio://voicera-calls/org-1/call-abc-123/recording.wav",
    )
    storage_cls.return_value.object_exists.return_value = False
    storage_cls.parse_minio_url = MinIOStorage.parse_minio_url
    client = _make_client()
    response = client.get("/api/v1/calls/call-abc-123/recording")
    assert response.status_code == 404
