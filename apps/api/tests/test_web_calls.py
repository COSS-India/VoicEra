"""Web call registration API tests."""

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


def _websocket_agent(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "agent_id": "agent-ws-1",
        "org_id": "org-1",
        "name": "WS Agent",
        "status": "active",
        "agent_category": "websocket",
        "created_by": "admin@example.com",
        "telephony": None,
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


def _telephony_agent() -> dict[str, Any]:
    return {
        "agent_id": "agent-tel-1",
        "org_id": "org-1",
        "name": "Tel Agent",
        "status": "active",
        "agent_category": "telephony",
        "telephony": {"provider": "vobiz"},
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
    }


class _FakeCollection:
    def __init__(self, store: dict[Any, dict[str, Any]], key_fn) -> None:
        self._store = store
        self._key_fn = key_fn

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
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


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(calls.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _admin_user
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_stores() -> None:
    _CALL_STORE.clear()
    _AGENT_STORE.clear()


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
def test_register_web_call_happy_path(
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-ws-1")] = _websocket_agent()
    client = _make_client()
    response = client.post(
        "/api/v1/calls/web",
        json={
            "agent_id": "agent-ws-1",
            "custom_variables": {"name": "Jane"},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["call_type"] == "web"
    assert body["status"] == "in_progress"
    assert body["agent_id"] == "agent-ws-1"
    assert body["custom_variables"] == {"name": "Jane"}
    assert len(_CALL_STORE) == 1
    stored = next(iter(_CALL_STORE.values()))
    assert stored["call_type"] == "web"
    assert stored["provider_call_sid"] == f"web-{stored['call_id']}"
    assert stored["from_number"] == "browser"
    assert stored["to_number"] == "agent"
    assert stored["telephony_provider"] is None


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
def test_register_web_call_rejects_telephony_agent(
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-tel-1")] = _telephony_agent()
    client = _make_client()
    response = client.post(
        "/api/v1/calls/web",
        json={"agent_id": "agent-tel-1"},
    )
    assert response.status_code == 422
    assert "websocket" in response.json()["detail"].lower()
    assert len(_CALL_STORE) == 0


@_patch_db("app.services.call_log_service.get_database")
@_patch_db("app.services.agent_service.get_database")
def test_register_web_call_agent_not_found(
    _agents_db: MagicMock,
    _calls_db: MagicMock,
) -> None:
    client = _make_client()
    response = client.post(
        "/api/v1/calls/web",
        json={"agent_id": "missing-agent"},
    )
    assert response.status_code == 404
