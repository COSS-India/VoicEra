"""Outbound call API and service tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import calls
from app.services import call_log_service, outbound_call_service
from app.services.agent_service import AgentNotFoundError
from app.services.outbound_call_service import OutboundCallError

_CALL_STORE: dict[str, dict[str, Any]] = {}
_AGENT_STORE: dict[tuple[str, str], dict[str, Any]] = {}
_PHONE_STORE: dict[str, dict[str, Any]] = {}


def _admin_user() -> dict[str, Any]:
    return {
        "email": "admin@example.com",
        "org_id": "org-1",
        "role": "admin",
    }


def _other_org_admin() -> dict[str, Any]:
    return {
        "email": "other@example.com",
        "org_id": "org-2",
        "role": "admin",
    }


def _telephony_agent(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "agent_id": "agent-1",
        "org_id": "org-1",
        "name": "Tel Agent",
        "status": "active",
        "agent_category": "telephony",
        "created_by": "admin@example.com",
        "linked_phone_number": "+15559876543",
        "telephony": {
            "provider": "vobiz",
            "application_id": "app-123",
            "answer_url": "https://voice.example.com/answer?agent_id=agent-1&org_id=org-1",
        },
        "config": {
            "schema_version": 1,
            "prompts": {
                "system_prompt": "You are helpful.",
                "greeting_message": "Hello!",
            },
            "behaviour": {},
            "language": {"primary": "en", "secondary": []},
            "models": {
                "stt_config": {"provider": "openai", "model": "gpt-4o-transcribe"},
                "tts_config": {
                    "provider": "openai",
                    "model": "gpt-4o-mini-tts",
                    "voice": "alloy",
                },
                "llm_config": {"provider": "openai", "model": "gpt-4o-mini"},
            },
            "knowledge_base": {"enabled": False, "document_ids": [], "top_k": 5},
        },
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    doc.update(overrides)
    return doc


class _FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, key: str, direction: int) -> _FakeCursor:
        reverse = direction == -1
        self._docs = sorted(
            self._docs,
            key=lambda doc: doc.get(key) or "",
            reverse=reverse,
        )
        return self

    def skip(self, count: int) -> _FakeCursor:
        self._docs = self._docs[max(0, count) :]
        return self

    def limit(self, count: int) -> _FakeCursor:
        self._docs = self._docs[: max(0, count)]
        return self

    def __iter__(self):
        return iter(self._docs)


class _FakeCollection:
    def __init__(self, store: dict[Any, dict[str, Any]], key_fn) -> None:
        self._store = store
        self._key_fn = key_fn

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self._store.values():
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    def find(self, query: dict[str, Any]) -> _FakeCursor:
        docs = [
            dict(doc)
            for doc in self._store.values()
            if all(doc.get(k) == v for k, v in query.items())
        ]
        return _FakeCursor(docs)

    def count_documents(self, query: dict[str, Any]) -> int:
        return sum(
            1
            for doc in self._store.values()
            if all(doc.get(k) == v for k, v in query.items())
        )

    def insert_one(self, doc: dict[str, Any]) -> None:
        key = self._key_fn(doc)
        self._store[key] = dict(doc)

    def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> MagicMock:
        doc = self.find_one(query)
        result = MagicMock()
        if not doc:
            result.matched_count = 0
            result.modified_count = 0
            return result
        key = self._key_fn(doc)
        updated = dict(doc)
        if "$set" in update:
            updated.update(update["$set"])
        self._store[key] = updated
        result.matched_count = 1
        result.modified_count = 1
        return result


def _fake_db() -> dict[str, Any]:
    return {
        "CallLogs": _FakeCollection(_CALL_STORE, lambda d: d["call_id"]),
        "Agents": _FakeCollection(
            _AGENT_STORE,
            lambda d: (d["org_id"], d["agent_id"]),
        ),
        "PhoneNumbers": _FakeCollection(
            _PHONE_STORE,
            lambda d: d["phone_number"],
        ),
    }


def _patch_db(target: str):
    return patch(target, side_effect=_fake_db)


def _make_client(user_fn=_admin_user) -> TestClient:
    app = FastAPI()
    app.include_router(calls.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = user_fn
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_stores() -> None:
    _CALL_STORE.clear()
    _AGENT_STORE.clear()
    _PHONE_STORE.clear()


@pytest.fixture(autouse=True)
def patch_voice_server_url() -> None:
    with patch(
        "app.services.agent_telephony_service.settings.VOICE_SERVER_BASE_URL",
        "https://voice.example.com",
    ):
        yield


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
@_patch_db("app.services.phone_number_service.get_database")
@patch(
    "app.services.outbound_call_service.get_provider_dial_credentials",
    return_value={
        "auth_id": "auth-id",
        "auth_token": "auth-token",
        "base_url": "https://api.vobiz.example.com",
    },
)
@patch(
    "app.services.outbound_call_service.initiate_outbound",
    new_callable=AsyncMock,
    return_value={
        "status": "success",
        "message": "Call initiated successfully",
        "call_uuid": "provider-sid-123",
    },
)
def test_outbound_call_happy_path(
    dial_mock: AsyncMock,
    _creds: MagicMock,
    _phones_db: MagicMock,
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent()
    client = _make_client()

    response = client.post(
        "/api/v1/calls/outbound",
        json={
            "agent_id": "agent-1",
            "to_number": "+14155551234",
            "custom_variables": {"customer_name": "Jane"},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ringing"
    assert body["provider_call_sid"] == "provider-sid-123"
    assert body["from_number"] == "+15559876543"
    assert body["to_number"] == "+14155551234"
    assert body["custom_variables"] == {"customer_name": "Jane"}
    assert len(_CALL_STORE) == 1
    stored = next(iter(_CALL_STORE.values()))
    assert stored["status"] == "ringing"
    assert stored["provider_call_sid"] == "provider-sid-123"
    assert stored["custom_variables"] == {"customer_name": "Jane"}
    assert stored["start_time_utc"]
    assert stored["call_response"] == "pending"
    dial_mock.assert_awaited_once()


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
@_patch_db("app.services.phone_number_service.get_database")
@patch(
    "app.services.outbound_call_service.get_provider_dial_credentials",
    return_value={
        "auth_id": "auth-id",
        "auth_token": "auth-token",
        "base_url": "https://api.vobiz.example.com",
    },
)
@patch(
    "app.services.outbound_call_service.initiate_outbound",
    new_callable=AsyncMock,
    return_value={
        "status": "success",
        "call_uuid": "sid-1",
    },
)
def test_custom_variables_persisted(
    _dial: AsyncMock,
    _creds: MagicMock,
    _phones_db: MagicMock,
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent()
    client = _make_client()
    response = client.post(
        "/api/v1/calls/outbound",
        json={
            "agent_id": "agent-1",
            "to_number": "+14155551234",
            "custom_variables": {"account_id": "ACC-99", "tier": "gold"},
        },
    )
    assert response.status_code == 201
    stored = next(iter(_CALL_STORE.values()))
    assert stored["custom_variables"] == {"account_id": "ACC-99", "tier": "gold"}


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
@patch(
    "app.services.outbound_call_service.initiate_outbound",
    new_callable=AsyncMock,
)
def test_missing_agent_returns_404(
    _dial: AsyncMock,
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    client = _make_client()
    response = client.post(
        "/api/v1/calls/outbound",
        json={"agent_id": "missing", "to_number": "+14155551234"},
    )
    assert response.status_code == 404
    assert len(_CALL_STORE) == 0
    _dial.assert_not_awaited()


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
@patch(
    "app.services.outbound_call_service.initiate_outbound",
    new_callable=AsyncMock,
)
def test_non_telephony_agent_returns_422(
    _dial: AsyncMock,
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent(
        agent_category="websocket",
        telephony=None,
        linked_phone_number=None,
    )
    client = _make_client()
    response = client.post(
        "/api/v1/calls/outbound",
        json={"agent_id": "agent-1", "to_number": "+14155551234"},
    )
    assert response.status_code == 422
    assert "telephony" in response.json()["detail"].lower()
    _dial.assert_not_awaited()


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
@_patch_db("app.services.phone_number_service.get_database")
@patch(
    "app.services.outbound_call_service.initiate_outbound",
    new_callable=AsyncMock,
)
def test_no_caller_id_returns_422(
    _dial: AsyncMock,
    _phones_db: MagicMock,
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent(linked_phone_number=None)
    client = _make_client()
    response = client.post(
        "/api/v1/calls/outbound",
        json={"agent_id": "agent-1", "to_number": "+14155551234"},
    )
    assert response.status_code == 422
    assert "caller id" in response.json()["detail"].lower()
    _dial.assert_not_awaited()


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
@_patch_db("app.services.phone_number_service.get_database")
@patch(
    "app.services.outbound_call_service.get_provider_dial_credentials",
    return_value={
        "auth_id": "auth-id",
        "auth_token": "auth-token",
        "base_url": "https://api.vobiz.example.com",
    },
)
@patch(
    "app.services.outbound_call_service.initiate_outbound",
    new_callable=AsyncMock,
    return_value={"status": "fail", "message": "Provider rejected call"},
)
def test_telephony_dial_failure_marks_call_failed(
    _dial: AsyncMock,
    _creds: MagicMock,
    _phones_db: MagicMock,
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent()
    client = _make_client()
    response = client.post(
        "/api/v1/calls/outbound",
        json={"agent_id": "agent-1", "to_number": "+14155551234"},
    )
    assert response.status_code == 502
    stored = next(iter(_CALL_STORE.values()))
    assert stored["status"] == "failed"
    assert stored["call_response"] == "failed"
    assert stored["error_message"]


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
@patch(
    "app.services.outbound_call_service.initiate_outbound",
    new_callable=AsyncMock,
)
def test_org_isolation_returns_404(
    _dial: AsyncMock,
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent(org_id="org-1")
    client = _make_client(_other_org_admin)
    response = client.post(
        "/api/v1/calls/outbound",
        json={"agent_id": "agent-1", "to_number": "+14155551234"},
    )
    assert response.status_code == 404
    _dial.assert_not_awaited()


@pytest.mark.asyncio
@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
@_patch_db("app.services.phone_number_service.get_database")
@patch(
    "app.services.outbound_call_service.get_provider_dial_credentials",
    return_value={
        "auth_id": "auth-id",
        "auth_token": "auth-token",
        "base_url": "https://api.vobiz.example.com",
    },
)
@patch(
    "app.services.outbound_call_service.initiate_outbound",
    new_callable=AsyncMock,
    return_value={"status": "success", "call_uuid": "sid-abc"},
)
async def test_call_log_created_with_initiated_before_dial(
    dial_mock: AsyncMock,
    _creds: MagicMock,
    _phones_db: MagicMock,
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent()
    statuses_seen: list[str] = []

    original_update = call_log_service.update_call_log

    def _track_update(call_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if "status" in patch:
            statuses_seen.append(patch["status"])
        return original_update(call_id, patch)

    with patch.object(call_log_service, "update_call_log", side_effect=_track_update):
        await outbound_call_service.initiate_outbound_call(
            "org-1",
            "agent-1",
            "+14155551234",
        )

    stored = next(iter(_CALL_STORE.values()))
    assert stored["call_type"] == "outbound"
    assert stored["start_time_utc"]
    assert stored["call_response"] == "pending"
    assert "agent_config" not in stored
    assert "inbound" not in stored
    assert "initiated_at" not in stored
    assert "call_busy" not in stored
    assert "ringing" in statuses_seen
    dial_mock.assert_awaited_once()
    answer_url = dial_mock.await_args.kwargs["answer_url"]
    assert "call_id=" in answer_url
    assert stored["call_id"] in answer_url


@pytest.mark.asyncio
@_patch_db("app.services.agent_service.get_database")
async def test_get_agent_not_found(_agents_db: MagicMock) -> None:
    with pytest.raises(AgentNotFoundError):
        from app.services import agent_service

        agent_service.get_agent("org-1", "nope")


@pytest.mark.asyncio
async def test_outbound_call_error_attributes() -> None:
    err = OutboundCallError("bad", status_code=404)
    assert err.status_code == 404
    assert err.message == "bad"


def _sample_call_doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "call_id": "call-abc-123",
        "org_id": "org-1",
        "agent_id": "agent-1",
        "agent_name": "Tel Agent",
        "call_type": "outbound",
        "status": "ringing",
        "call_response": "pending",
        "from_number": "+15559876543",
        "to_number": "+14155551234",
        "telephony_provider": "vobiz",
        "provider_call_sid": "provider-sid-123",
        "custom_variables": {"customer_name": "Jane", "account_id": "ACC-1"},
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "start_time_utc": "2026-01-01T00:00:00+00:00",
        "end_time_utc": None,
        "duration": None,
        "recording_url": None,
        "transcript_url": None,
        "error_message": None,
    }
    doc.update(overrides)
    return doc


@_patch_db("app.services.call_log_service.get_database")
@patch(
    "app.routers.calls.org_service.get_organisation",
    return_value={"org_id": "org-1", "name": "Org One"},
)
def test_list_org_calls_happy_path(
    _org: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    _CALL_STORE["call-def-456"] = _sample_call_doc(
        call_id="call-def-456",
        created_at="2026-01-02T00:00:00+00:00",
    )
    _CALL_STORE["call-other-org"] = _sample_call_doc(
        call_id="call-other-org",
        org_id="org-2",
    )
    client = _make_client()

    response = client.get("/api/v1/calls/org/org-1")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert len(body["calls"]) == 2
    assert body["calls"][0]["call_id"] == "call-def-456"
    assert body["calls"][1]["call_id"] == "call-abc-123"


@_patch_db("app.services.call_log_service.get_database")
@patch(
    "app.routers.calls.org_service.get_organisation",
    return_value={"org_id": "org-1", "name": "Org One"},
)
def test_list_org_calls_pagination(
    _org: MagicMock,
    _calls_db: MagicMock,
) -> None:
    for idx in range(3):
        _CALL_STORE[f"call-{idx}"] = _sample_call_doc(
            call_id=f"call-{idx}",
            created_at=f"2026-01-0{idx + 1}T00:00:00+00:00",
        )
    client = _make_client()

    response = client.get("/api/v1/calls/org/org-1?limit=1&offset=1")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert len(body["calls"]) == 1
    assert body["calls"][0]["call_id"] == "call-1"


@patch("app.routers.calls.org_service.get_organisation", return_value=None)
def test_list_org_calls_org_not_found(_org: MagicMock) -> None:
    client = _make_client()
    response = client.get("/api/v1/calls/org/org-1")
    assert response.status_code == 404


@patch(
    "app.routers.calls.org_service.get_organisation",
    return_value={"org_id": "org-2", "name": "Org Two"},
)
@patch("app.routers.calls.member_service.get_membership", return_value=None)
def test_list_org_calls_forbidden(
    _membership: MagicMock,
    _org: MagicMock,
) -> None:
    client = _make_client()
    response = client.get("/api/v1/calls/org/org-2")
    assert response.status_code == 403


@_patch_db("app.services.call_log_service.get_database")
def test_get_call_happy_path(_calls_db: MagicMock) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc()
    client = _make_client()
    response = client.get("/api/v1/calls/call-abc-123")
    assert response.status_code == 200
    body = response.json()
    assert body["call_id"] == "call-abc-123"
    assert body["custom_variables"] == {
        "customer_name": "Jane",
        "account_id": "ACC-1",
    }
    assert body["call_type"] == "outbound"
    assert body["status"] == "ringing"


@_patch_db("app.services.call_log_service.get_database")
def test_get_call_not_found(_calls_db: MagicMock) -> None:
    client = _make_client()
    response = client.get("/api/v1/calls/missing-call-id")
    assert response.status_code == 404


@_patch_db("app.services.call_log_service.get_database")
def test_get_call_org_isolation(_calls_db: MagicMock) -> None:
    _CALL_STORE["call-abc-123"] = _sample_call_doc(org_id="org-1")
    client = _make_client(_other_org_admin)
    response = client.get("/api/v1/calls/call-abc-123")
    assert response.status_code == 404
