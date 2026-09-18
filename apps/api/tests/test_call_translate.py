"""HTTP-level tests for POST /calls/{call_id}/translate."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import calls
from app.services.translation_service import TranslationError
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
        "status": "completed",
        "from_number": "+15559876543",
        "to_number": "+14155551234",
        "start_time_utc": "2026-01-01T00:00:00+00:00",
        "end_time_utc": "2026-01-01T00:01:00+00:00",
        "duration": 60.0,
        "recording_url": None,
        "transcript_url": "minio://voicera-calls/org-1/call-abc-123/transcript.txt",
    }
    doc.update(overrides)
    return doc


@pytest.fixture(autouse=True)
def clear_store() -> None:
    _CALL_STORE.clear()


def _minio_storage_mock(storage_cls: MagicMock, raw_transcript: bytes = b"[00:01] user: hello") -> MagicMock:
    storage_cls.parse_minio_url = MinIOStorage.parse_minio_url
    storage = storage_cls.return_value
    storage.object_exists.return_value = True
    response_obj = MagicMock()
    response_obj.read.return_value = raw_transcript
    storage.client.get_object.return_value = response_obj
    return storage


@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.translate_transcript")
@patch("app.routers.calls.MinIOStorage")
def test_translate_returns_translated_text(
    storage_cls: MagicMock,
    mock_translate: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    _minio_storage_mock(storage_cls)
    mock_translate.return_value = "[00:01] user: नमस्ते"

    client = _make_client()
    response = client.post("/api/v1/calls/call-abc-123/translate?target_lang=hi")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "translated_text": "[00:01] user: नमस्ते",
        "target_lang": "hi",
        "source_lang": None,
    }
    mock_translate.assert_called_once_with("[00:01] user: hello", "hi")


@_patch_db("app.services.call_log_service.get_database")
def test_translate_nonexistent_call_returns_404(_calls_db: MagicMock) -> None:
    client = _make_client()
    response = client.post("/api/v1/calls/does-not-exist/translate?target_lang=hi")
    assert response.status_code == 404


@_patch_db("app.services.call_log_service.get_database")
def test_translate_missing_transcript_url_returns_404(_calls_db: MagicMock) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc(transcript_url=None)
    client = _make_client()
    response = client.post("/api/v1/calls/call-abc-123/translate?target_lang=hi")
    assert response.status_code == 404
    assert "Transcript not found" in response.json()["detail"]


@_patch_db("app.services.call_log_service.get_database")
def test_translate_malformed_transcript_url_returns_400(_calls_db: MagicMock) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc(transcript_url="not-a-minio-url")
    client = _make_client()
    response = client.post("/api/v1/calls/call-abc-123/translate?target_lang=hi")
    assert response.status_code == 400


@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.MinIOStorage")
def test_translate_missing_transcript_object_returns_404(
    storage_cls: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    storage_cls.parse_minio_url = MinIOStorage.parse_minio_url
    storage_cls.return_value.object_exists.return_value = False

    client = _make_client()
    response = client.post("/api/v1/calls/call-abc-123/translate?target_lang=hi")
    assert response.status_code == 404
    assert "Transcript file not found" in response.json()["detail"]


@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.translate_transcript")
@patch("app.routers.calls.MinIOStorage")
def test_translate_oversized_transcript_returns_413(
    storage_cls: MagicMock,
    mock_translate: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    _minio_storage_mock(storage_cls)
    mock_translate.side_effect = TranslationError(
        "Transcript is too long to translate in one request (50001 chars, limit 50000)."
    )

    client = _make_client()
    response = client.post("/api/v1/calls/call-abc-123/translate?target_lang=hi")

    assert response.status_code == 413
    assert "too long" in response.json()["detail"]


@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.translate_transcript")
@patch("app.routers.calls.MinIOStorage")
def test_translate_generic_provider_failure_returns_502(
    storage_cls: MagicMock,
    mock_translate: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    _minio_storage_mock(storage_cls)
    mock_translate.side_effect = TranslationError("Translation is not configured (missing API key).")

    client = _make_client()
    response = client.post("/api/v1/calls/call-abc-123/translate?target_lang=hi")

    assert response.status_code == 502
    assert "not configured" in response.json()["detail"]


@_patch_db("app.services.call_log_service.get_database")
def test_translate_org_isolation(_calls_db: MagicMock) -> None:
    """A call belonging to a different org must 404, not leak its transcript."""
    _CALL_STORE["call-abc-123"] = _sample_call_doc(org_id="org-1")
    client = _make_client(_other_org_admin)
    response = client.post("/api/v1/calls/call-abc-123/translate?target_lang=hi")
    assert response.status_code == 404


@_patch_db("app.services.call_log_service.get_database")
@patch("app.routers.calls.translate_transcript")
@patch("app.routers.calls.MinIOStorage")
def test_translate_requires_target_lang_query_param(
    storage_cls: MagicMock,
    mock_translate: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    _minio_storage_mock(storage_cls)

    client = _make_client()
    response = client.post("/api/v1/calls/call-abc-123/translate")

    assert response.status_code == 422
    mock_translate.assert_not_called()


def test_translate_requires_authentication() -> None:
    app = FastAPI()
    app.include_router(calls.router, prefix="/api/v1")
    client = TestClient(app)

    response = client.post("/api/v1/calls/call-abc-123/translate?target_lang=hi")
    assert response.status_code in (401, 403)
