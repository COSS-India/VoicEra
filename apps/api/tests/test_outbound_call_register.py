"""Outbound call registration API tests (stream-time, no dial)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import calls

_CALL_STORE: dict[str, dict[str, Any]] = {}
_AGENT_STORE: dict[tuple[str, str], dict[str, Any]] = {}


def _admin_user() -> dict[str, Any]:
    return {
        "email": "admin@example.com",
        "org_id": "org-1",
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
        "linked_phone_number": "+919876543210",
        "telephony": {
            "provider": "vi",
            "application_id": "app-123",
            "answer_url": "https://voice.example.com/vi/stream",
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
def test_register_outbound_call_happy_path(
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent()
    client = _make_client()
    response = client.post(
        "/api/v1/calls/outbound/register",
        json={
            "agent_id": "agent-1",
            "provider_call_sid": "obd-sid-1",
            "from_number": "+919876543210",
            "to_number": "unknown",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["call_type"] == "outbound"
    assert body["status"] == "in_progress"
    assert body["provider_call_sid"] == "obd-sid-1"
    assert body["from_number"] == "+919876543210"
    assert body["to_number"] == "unknown"
    assert len(_CALL_STORE) == 1
    stored = next(iter(_CALL_STORE.values()))
    assert stored["call_type"] == "outbound"
    assert stored["telephony_provider"] == "vi"


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
def test_register_outbound_call_idempotent(
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent()
    client = _make_client()
    payload = {
        "agent_id": "agent-1",
        "provider_call_sid": "obd-sid-dup",
        "from_number": "9876543210",
        "to_number": "unknown",
    }
    first = client.post("/api/v1/calls/outbound/register", json=payload)
    second = client.post("/api/v1/calls/outbound/register", json=payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["call_id"] == second.json()["call_id"]
    assert len(_CALL_STORE) == 1


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
def test_register_outbound_reuses_dial_time_log(
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    """Dial-time outbound logs keep the real to_number when stream registers."""
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent()
    existing = {
        "call_id": "dial-call-1",
        "provider_call_sid": "obd-sid-dial",
        "org_id": "org-1",
        "agent_id": "agent-1",
        "call_type": "outbound",
        "status": "ringing",
        "from_number": "+919876543210",
        "to_number": "+919999999999",
    }
    _CALL_STORE["dial-call-1"] = existing
    client = _make_client()
    response = client.post(
        "/api/v1/calls/outbound/register",
        json={
            "agent_id": "agent-1",
            "provider_call_sid": "obd-sid-dial",
            "from_number": "9876543210",
            "to_number": "unknown",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["call_id"] == "dial-call-1"
    assert body["to_number"] == "+919999999999"
    assert len(_CALL_STORE) == 1


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
def test_register_outbound_normalizes_indian_from_number(
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent()
    client = _make_client()
    response = client.post(
        "/api/v1/calls/outbound/register",
        json={
            "agent_id": "agent-1",
            "provider_call_sid": "obd-sid-india",
            "from_number": "9876543210",
            "to_number": "unknown",
        },
    )
    assert response.status_code == 201
    assert response.json()["from_number"] == "+919876543210"
