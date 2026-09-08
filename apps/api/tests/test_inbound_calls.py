"""Inbound call registration API tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import calls
from app.services.agent_service import AgentNotFoundError

_CALL_STORE: dict[str, dict[str, Any]] = {}
_AGENT_STORE: dict[tuple[str, str], dict[str, Any]] = {}


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


class _FakeCollection:
    def __init__(self, store: dict[Any, dict[str, Any]], key_fn) -> None:
        self._store = store
        self._key_fn = key_fn

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        if "provider_call_sid" in query:
            for doc in self._store.values():
                if (
                    doc.get("org_id") == query.get("org_id")
                    and doc.get("provider_call_sid") == query.get("provider_call_sid")
                ):
                    return dict(doc)
            return None
        for doc in self._store.values():
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    def insert_one(self, doc: dict[str, Any]) -> None:
        key = self._key_fn(doc)
        self._store[key] = dict(doc)

    def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> MagicMock:
        doc = self.find_one(query)
        result = MagicMock()
        if not doc:
            result.matched_count = 0
            return result
        updated = dict(doc)
        if "$set" in update:
            updated.update(update["$set"])
        self._store[self._key_fn(doc)] = updated
        result.matched_count = 1
        return result


def _fake_db() -> dict[str, Any]:
    return {
        "CallLogs": _FakeCollection(_CALL_STORE, lambda d: d["call_id"]),
        "Agents": _FakeCollection(
            _AGENT_STORE,
            lambda d: (d["org_id"], d["agent_id"]),
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


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
def test_register_inbound_call_happy_path(
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent()
    client = _make_client()
    response = client.post(
        "/api/v1/calls/inbound",
        json={
            "agent_id": "agent-1",
            "provider_call_sid": "inbound-sid-1",
            "from_number": "+15551234567",
            "to_number": "+15559876543",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["call_type"] == "inbound"
    assert body["status"] == "in_progress"
    assert body["provider_call_sid"] == "inbound-sid-1"
    assert body["from_number"] == "+15551234567"
    assert body["to_number"] == "+15559876543"
    assert len(_CALL_STORE) == 1
    stored = next(iter(_CALL_STORE.values()))
    assert stored["call_type"] == "inbound"
    assert stored["custom_variables"] == {}


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
def test_register_inbound_call_idempotent(
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent()
    client = _make_client()
    payload = {
        "agent_id": "agent-1",
        "provider_call_sid": "inbound-sid-dup",
        "from_number": "+15551234567",
        "to_number": "+15559876543",
    }
    first = client.post("/api/v1/calls/inbound", json=payload)
    second = client.post("/api/v1/calls/inbound", json=payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["call_id"] == second.json()["call_id"]
    assert len(_CALL_STORE) == 1


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
def test_register_inbound_call_backfills_unknown_from_number(
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent()
    client = _make_client()
    sid = "inbound-sid-backfill"
    assert client.post(
        "/api/v1/calls/inbound",
        json={
            "agent_id": "agent-1",
            "provider_call_sid": sid,
            "from_number": "unknown",
            "to_number": "unknown",
        },
    ).status_code == 201
    stored = next(iter(_CALL_STORE.values()))
    assert stored["to_number"] == "+15559876543"

    second = client.post(
        "/api/v1/calls/inbound",
        json={
            "agent_id": "agent-1",
            "provider_call_sid": sid,
            "from_number": "+15551234567",
            "to_number": "unknown",
        },
    )
    assert second.status_code == 201
    assert second.json()["from_number"] == "+15551234567"
    assert second.json()["to_number"] == "+15559876543"


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
def test_register_inbound_call_missing_agent(
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    client = _make_client()
    response = client.post(
        "/api/v1/calls/inbound",
        json={
            "agent_id": "missing",
            "provider_call_sid": "sid-1",
            "from_number": "+1",
            "to_number": "+2",
        },
    )
    assert response.status_code == 404
    assert len(_CALL_STORE) == 0


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
def test_register_inbound_call_org_isolation(
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent(org_id="org-1")
    client = _make_client(_other_org_admin)
    response = client.post(
        "/api/v1/calls/inbound",
        json={
            "agent_id": "agent-1",
            "provider_call_sid": "sid-1",
            "from_number": "+15551234567",
            "to_number": "+15559876543",
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
@_patch_db("app.services.agent_service.get_database")
async def test_register_inbound_raises_when_agent_missing(_agents_db: MagicMock) -> None:
    from app.services.inbound_call_service import InboundCallError, register_inbound_call

    with pytest.raises(InboundCallError) as exc_info:
        register_inbound_call(
            "org-1",
            "missing",
            provider_call_sid="sid-1",
            from_number="+1",
            to_number="+2",
        )
    assert exc_info.value.status_code == 404
