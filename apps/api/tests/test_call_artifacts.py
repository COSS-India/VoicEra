"""Call artifact PATCH and MinIO proxy route tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import urllib3
from pymongo.errors import PyMongoError
from app.auth import BOT_SERVICE_EMAIL, get_current_user, verify_api_key
from app.services.eventlog import store
from app.routers import calls
from app.storage.minio_client import MinIOStorage
from fastapi import FastAPI
from fastapi.testclient import TestClient
from minio.error import S3Error

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
    app.dependency_overrides[verify_api_key] = lambda: True
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


@pytest.fixture(autouse=True)
def agent_names() -> dict[str, str]:
    """Current agent names by id; a missing id is a deleted agent."""
    names = {"agent-1": "Support Bot"}
    with patch(
        "app.routers.calls.agent_service.get_agent_name",
        side_effect=lambda org_id, agent_id: names.get(agent_id),
    ):
        yield names


@pytest.fixture(autouse=True)
def events() -> list[dict[str, Any]]:
    """Events emitted during the test, captured instead of written."""
    captured: list[dict[str, Any]] = []
    with patch.object(store, "insert", side_effect=captured.append):
        yield captured


@_patch_db("app.services.call_log_service.get_database")
def test_patch_call_sets_minio_urls(_calls_db: MagicMock) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    client = _make_client()

    response = client.patch(
        "/api/v1/calls/call-abc-123",
        json={
            "transcript_url": "minio://voicera-calls/org-1/call-abc-123/transcript.txt",
            "recording_url": "minio://voicera-calls/org-1/call-abc-123/recording.wav",
            "provider_recording_url": (
                "minio://voicera-calls/org-1/call-abc-123/provider_recording.wav"
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transcript_url"] == "/api/v1/calls/call-abc-123/transcript"
    assert body["recording_url"] == "/api/v1/calls/call-abc-123/recording"
    assert (
        body["provider_recording_url"]
        == "/api/v1/calls/call-abc-123/provider-recording"
    )
    stored = _CALL_STORE["call-abc-123"]
    assert stored["transcript_url"].startswith("minio://")
    assert stored["recording_url"].startswith("minio://")
    assert stored["provider_recording_url"].startswith("minio://")


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


@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.MinIOStorage")
def test_get_call_provider_recording_proxies_minio(
    storage_cls: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc(
        provider_recording_url=(
            "minio://voicera-calls/org-1/call-abc-123/provider_recording.wav"
        ),
    )
    storage = storage_cls.return_value
    storage.object_exists.return_value = True
    storage_cls.parse_minio_url = MinIOStorage.parse_minio_url

    response_obj = MagicMock()
    response_obj.stream.return_value = [b"PROV", b"REC"]
    storage.client.get_object.return_value = response_obj

    client = _make_client()
    response = client.get("/api/v1/calls/call-abc-123/provider-recording")

    assert response.status_code == 200
    assert response.content == b"PROVREC"
    storage.object_exists.assert_called_once_with(
        "voicera-calls",
        "org-1/call-abc-123/provider_recording.wav",
    )


@_patch_db("app.services.call_log_service.get_database")
def test_get_call_by_provider_sid_internal(_calls_db: MagicMock) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc(
        provider_call_sid="vi-stream-1",
        provider_recording_url=(
            "minio://voicera-calls/org-1/call-abc-123/provider_recording.wav"
        ),
    )
    client = _make_client()
    response = client.get("/api/v1/calls/by-provider-sid/vi-stream-1")
    assert response.status_code == 200
    body = response.json()
    assert body["call_id"] == "call-abc-123"
    assert body["org_id"] == "org-1"
    assert (
        body["provider_recording_url"]
        == "/api/v1/calls/call-abc-123/provider-recording"
    )


@_patch_db("app.services.call_log_service.get_database")
def test_get_call_by_provider_sid_not_found(_calls_db: MagicMock) -> None:
    client = _make_client()
    response = client.get("/api/v1/calls/by-provider-sid/missing-sid")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Access audit events
# ---------------------------------------------------------------------------

_ARTIFACT_URLS = {
    "recording": ("recording_url", "recording.wav"),
    "provider-recording": ("provider_recording_url", "provider_recording.wav"),
    "transcript": ("transcript_url", "transcript.txt"),
}


def _serve(storage_cls: MagicMock, body: bytes = b"DATA") -> MagicMock:
    storage = storage_cls.return_value
    storage.object_exists.return_value = True
    storage_cls.parse_minio_url = MinIOStorage.parse_minio_url
    response_obj = MagicMock()
    response_obj.stream.return_value = [body]
    storage.client.get_object.return_value = response_obj
    return storage


def _store_call_with_all_artifacts(call_id: str = "call-abc-123") -> None:
    _CALL_STORE[call_id] = _sample_call_doc(
        call_id=call_id,
        **{
            field: f"minio://voicera-calls/org-1/{call_id}/{name}"
            for field, name in _ARTIFACT_URLS.values()
        },
    )


@pytest.mark.parametrize(
    ("path", "mode", "event_type"),
    [
        ("recording", None, "call.recording.viewed"),
        ("recording", "view", "call.recording.viewed"),
        ("recording", "download", "call.recording.downloaded"),
        ("provider-recording", "view", "call.provider_recording.viewed"),
        ("provider-recording", "download", "call.provider_recording.downloaded"),
        ("transcript", "view", "call.transcript.viewed"),
        ("transcript", "download", "call.transcript.downloaded"),
    ],
)
@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.MinIOStorage")
def test_artifact_access_is_recorded(
    storage_cls: MagicMock,
    _calls_db: MagicMock,
    path: str,
    mode: str | None,
    event_type: str,
    events: list[dict[str, Any]],
) -> None:
    _store_call_with_all_artifacts()
    _serve(storage_cls)
    query = f"?mode={mode}" if mode else ""

    response = _make_client().get(
        f"/api/v1/calls/call-abc-123/{path}{query}", headers={"User-Agent": "pytest"}
    )

    assert response.status_code == 200
    [event] = events
    assert event["type"] == event_type
    assert event["org_id"] == "org-1"
    assert event["outcome"] == "success"
    assert event["actor"] == {"type": "user", "id": "admin@example.com", "role": "admin"}
    assert event["target"] == {"type": "call", "id": "call-abc-123"}
    assert event["related"] == [{"type": "agent", "id": "agent-1", "name": "Support Bot"}]
    assert event["resource_keys"] == ["call:call-abc-123", "agent:agent-1"]
    assert event["data"] == {"object_key": f"org-1/call-abc-123/{_ARTIFACT_URLS[path][1]}"}
    assert event["context"]["user_agent"] == "pytest"


@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.MinIOStorage")
def test_bot_access_is_recorded_as_service(
    storage_cls: MagicMock, _calls_db: MagicMock, events: list[dict[str, Any]]
) -> None:
    _store_call_with_all_artifacts()
    _serve(storage_cls)
    bot = {"email": BOT_SERVICE_EMAIL, "org_id": "org-1", "role": "admin"}

    _make_client(lambda: bot).get("/api/v1/calls/call-abc-123/transcript")

    assert events[0]["actor"]["type"] == "service"


def test_invalid_mode_is_rejected(events: list[dict[str, Any]]) -> None:
    response = _make_client().get("/api/v1/calls/call-abc-123/recording?mode=stream")
    assert response.status_code == 422
    assert events == []


@pytest.mark.parametrize(
    ("doc", "exists", "status", "detail", "reason"),
    [
        (None, True, 404, None, "call_not_found"),
        ({}, True, 404, "Recording not found for this call", "artifact_missing"),
        (
            {"recording_url": "s3://bucket/key.wav"},
            True,
            400,
            "Invalid recording URL on call log",
            "invalid_artifact_url",
        ),
        (
            {"recording_url": "minio://voicera-calls/org-1/call-abc-123/recording.wav"},
            False,
            404,
            "Recording file not found: org-1/call-abc-123/recording.wav",
            "artifact_missing",
        ),
    ],
)
@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.MinIOStorage")
def test_artifact_failures_are_recorded(
    storage_cls: MagicMock,
    _calls_db: MagicMock,
    doc: dict[str, Any] | None,
    exists: bool,
    status: int,
    detail: str | None,
    reason: str,
    events: list[dict[str, Any]],
) -> None:
    if doc is not None:
        _CALL_STORE["call-abc-123"] = _sample_call_doc(**doc)
    storage_cls.return_value.object_exists.return_value = exists
    storage_cls.parse_minio_url = MinIOStorage.parse_minio_url

    response = _make_client().get("/api/v1/calls/call-abc-123/recording?mode=download")

    assert response.status_code == status
    if detail:
        assert response.json()["detail"] == detail
    [event] = events
    assert event["type"] == "call.recording.downloaded"
    assert event["outcome"] == "failure"
    assert event["data"] == {"reason": reason}
    # The agent is known only once the call itself is found.
    assert event.get("related") == (None if doc is None else [{"type": "agent", "id": "agent-1", "name": "Support Bot"}])


@pytest.mark.parametrize(
    "error",
    [
        S3Error("AccessDenied", "denied", "/r", "req", "host", None),
        urllib3.exceptions.MaxRetryError(None, "/r", "connection refused"),
    ],
)
@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.MinIOStorage")
def test_storage_failure_is_recorded_and_returns_503(
    storage_cls: MagicMock,
    _calls_db: MagicMock,
    error: Exception,
    events: list[dict[str, Any]],
) -> None:
    _store_call_with_all_artifacts()
    storage_cls.return_value.object_exists.side_effect = error
    storage_cls.parse_minio_url = MinIOStorage.parse_minio_url

    response = _make_client().get("/api/v1/calls/call-abc-123/transcript")

    assert response.status_code == 503
    assert response.json()["detail"] == "Call artifact storage is unavailable. Try again shortly."
    [event] = events
    assert event["type"] == "call.transcript.viewed"
    assert event["outcome"] == "failure"
    assert event["data"] == {"reason": "storage_unavailable"}


@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.MinIOStorage")
def test_other_org_call_is_recorded_as_not_found_in_callers_org(
    storage_cls: MagicMock, _calls_db: MagicMock, events: list[dict[str, Any]]
) -> None:
    _store_call_with_all_artifacts()

    response = _make_client(_other_org_admin).get("/api/v1/calls/call-abc-123/transcript")

    assert response.status_code == 404
    assert events[0]["org_id"] == "org-2"
    assert events[0]["data"] == {"reason": "call_not_found"}
    assert "related" not in events[0]
    storage_cls.return_value.object_exists.assert_not_called()


def test_missing_org_is_rejected_before_any_event(events: list[dict[str, Any]]) -> None:
    client = _make_client(lambda: {"email": "a@example.com", "org_id": None, "role": "admin"})
    response = client.get("/api/v1/calls/call-abc-123/recording")
    assert response.status_code == 400
    assert events == []


@pytest.mark.parametrize(
    ("path", "object_name", "filename"),
    [
        ("recording", "recording.wav", 'call-abc-123-recording.wav"'),
        ("provider-recording", "provider_recording.mp3", 'call-abc-123-provider-recording.mp3"'),
        ("transcript", "transcript.txt", 'call-abc-123-transcript.txt"'),
        ("transcript", "transcript.exe", 'call-abc-123-transcript.bin"'),
    ],
)
@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.MinIOStorage")
def test_download_sets_content_disposition(
    storage_cls: MagicMock,
    _calls_db: MagicMock,
    path: str,
    object_name: str,
    filename: str,
) -> None:
    field = _ARTIFACT_URLS[path][0]
    _CALL_STORE["call-abc-123"] = _sample_call_doc(
        **{field: f"minio://voicera-calls/org-1/call-abc-123/{object_name}"}
    )
    _serve(storage_cls)
    client = _make_client()

    download = client.get(f"/api/v1/calls/call-abc-123/{path}?mode=download")
    view = client.get(f"/api/v1/calls/call-abc-123/{path}")

    assert download.headers["content-disposition"] == f'attachment; filename="{filename}'
    assert "content-disposition" not in view.headers


@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.MinIOStorage")
def test_download_filename_is_sanitised_from_stored_call_id(
    storage_cls: MagicMock, _calls_db: MagicMock
) -> None:
    call_id = 'ab"c;\r\nx=..y'
    _CALL_STORE[call_id] = _sample_call_doc(
        call_id=call_id,
        transcript_url="minio://voicera-calls/org-1/c/transcript.txt",
    )
    _serve(storage_cls)

    response = _make_client().get(
        "/api/v1/calls/ab%22c%3B%0D%0Ax%3D..y/transcript?mode=download"
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="abcxy-transcript.txt"'
    )


@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.MinIOStorage")
def test_event_log_failure_does_not_break_playback(
    storage_cls: MagicMock, _calls_db: MagicMock
) -> None:
    _store_call_with_all_artifacts()
    _serve(storage_cls, body=b"RIFFWAVE")

    with patch.object(store, "insert", side_effect=RuntimeError("events down")):
        response = _make_client().get("/api/v1/calls/call-abc-123/recording")

    assert response.status_code == 200
    assert response.content == b"RIFFWAVE"


@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.MinIOStorage")
def test_deleted_agent_is_named_from_the_call_log(
    storage_cls: MagicMock,
    _calls_db: MagicMock,
    agent_names: dict[str, str],
    events: list[dict[str, Any]],
) -> None:
    _store_call_with_all_artifacts()
    _CALL_STORE["call-abc-123"]["agent_name"] = "Old Bot"
    agent_names.clear()
    _serve(storage_cls)

    _make_client().get("/api/v1/calls/call-abc-123/transcript")

    assert events[0]["related"] == [{"type": "agent", "id": "agent-1", "name": "Old Bot"}]


@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.MinIOStorage")
def test_campaign_call_relates_agent_and_campaign(
    storage_cls: MagicMock, _calls_db: MagicMock, events: list[dict[str, Any]]
) -> None:
    _store_call_with_all_artifacts()
    _CALL_STORE["call-abc-123"]["campaign_id"] = "camp-1"
    _serve(storage_cls)

    with patch(
        "app.services.call_log_service._campaign_names_by_id",
        return_value={"camp-1": "Diwali OBD"},
    ):
        _make_client().get("/api/v1/calls/call-abc-123/recording")

    [event] = events
    assert event["related"] == [
        {"type": "agent", "id": "agent-1", "name": "Support Bot"},
        {"type": "campaign", "id": "camp-1", "name": "Diwali OBD"},
    ]
    assert event["resource_keys"] == ["call:call-abc-123", "agent:agent-1", "campaign:camp-1"]


@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.MinIOStorage")
def test_failed_agent_name_lookup_still_serves_and_records(
    storage_cls: MagicMock, _calls_db: MagicMock, events: list[dict[str, Any]]
) -> None:
    _store_call_with_all_artifacts()
    _CALL_STORE["call-abc-123"]["agent_name"] = "Old Bot"
    _serve(storage_cls)

    with patch(
        "app.routers.calls.agent_service.get_agent_name",
        side_effect=PyMongoError("agents unavailable"),
    ):
        response = _make_client().get("/api/v1/calls/call-abc-123/recording")

    assert response.status_code == 200
    [event] = events
    assert event["outcome"] == "success"
    assert event["related"] == [{"type": "agent", "id": "agent-1", "name": "Old Bot"}]
