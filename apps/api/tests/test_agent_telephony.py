"""Agent telephony lifecycle tests (mocked provider calls)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.models.schemas import AgentCreateRequest, AgentUpdateRequest
from app.routers import agents
from app.services.agent_config_validation import AgentConfigValidationError
from app.services.agent_service import AgentConflictError, AgentNotFoundError
from app.services.agent_telephony_service import AgentTelephonyError

_STORE: dict[tuple[str, str], dict[str, Any]] = {}


def _admin_user() -> dict[str, Any]:
    return {
        "email": "admin@example.com",
        "org_id": "org-1",
        "role": "admin",
    }


def _valid_config() -> dict[str, Any]:
    return {
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
    }


def _telephony_attachment(provider: str = "vobiz", app_id: str = "app-123") -> dict[str, Any]:
    return {
        "provider": provider,
        "application_id": app_id,
        "answer_url": "https://voice.example.com/answer?agent_id=agent-1&org_id=org-1",
        "hangup_url": "https://voice.example.com/answer?agent_id=agent-1&org_id=org-1",
    }


def _full_agent_doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "agent_id": "agent-1",
        "org_id": "org-1",
        "name": "Tel Agent",
        "status": "active",
        "agent_category": "telephony",
        "created_by": "admin@example.com",
        "linked_phone_number": None,
        "telephony": _telephony_attachment(),
        "config": _valid_config(),
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    doc.update(overrides)
    return doc


async def _create(
    org_id: str,
    created_by_email: str,
    payload: AgentCreateRequest,
) -> dict[str, Any]:
    from app.services.agent_config_validation import validate_agent_config

    name = payload.name.strip()
    if not name:
        raise AgentConfigValidationError("name is required")
    if payload.agent_category == "telephony" and not payload.telephony_provider:
        raise AgentConfigValidationError(
            "telephony_provider is required when agent_category is telephony"
        )
    if payload.agent_category == "websocket" and payload.telephony_provider:
        raise AgentConfigValidationError(
            "telephony_provider must not be set when agent_category is websocket"
        )

    for (_org, _aid), doc in _STORE.items():
        if _org == org_id and doc["name"] == name:
            raise AgentConflictError(name)

    validated = validate_agent_config(payload.config)
    agent_id = f"agent-{len(_STORE) + 1}"

    telephony = None
    if payload.agent_category == "telephony":
        telephony = _telephony_attachment(str(payload.telephony_provider))

    doc = {
        "agent_id": agent_id,
        "org_id": org_id,
        "name": name,
        "status": "active",
        "agent_category": payload.agent_category,
        "created_by": created_by_email,
        "linked_phone_number": None,
        "telephony": telephony,
        "config": validated.model_dump(mode="python"),
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    _STORE[(org_id, agent_id)] = doc
    return dict(doc)


async def _update(
    org_id: str,
    agent_id: str,
    payload: AgentUpdateRequest,
) -> dict[str, Any]:
    doc = _STORE.get((org_id, agent_id))
    if not doc:
        raise AgentNotFoundError(agent_id)

    updated = dict(doc)
    if payload.name is not None:
        updated["name"] = payload.name.strip()
    if payload.agent_category is not None:
        updated["agent_category"] = payload.agent_category
    if payload.telephony_provider is not None or payload.agent_category is not None:
        category = updated["agent_category"]
        provider = payload.telephony_provider
        if category == "telephony":
            if provider is None and doc.get("telephony"):
                provider = doc["telephony"]["provider"]
            updated["telephony"] = _telephony_attachment(str(provider), "app-new")
        else:
            updated["telephony"] = None
    updated["updated_at"] = "2026-01-02T00:00:00+00:00"
    _STORE[(org_id, agent_id)] = updated
    return dict(updated)


async def _delete(org_id: str, agent_id: str) -> None:
    if (org_id, agent_id) not in _STORE:
        raise AgentNotFoundError(agent_id)
    del _STORE[(org_id, agent_id)]


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(agents.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _admin_user
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_store() -> None:
    _STORE.clear()


@patch(
    "app.services.agent_service.agent_telephony_service.provision_application",
    new_callable=AsyncMock,
)
def test_websocket_create_skips_telephony(provision_mock: AsyncMock) -> None:
    with patch("app.routers.agents.agent_service.create_agent", side_effect=_create):
        client = _make_client()
        response = client.post(
            "/api/v1/agents",
            json={
                "name": "WS Agent",
                "agent_category": "websocket",
                "config": _valid_config(),
            },
        )
    assert response.status_code == 201
    assert response.json()["telephony"] is None
    provision_mock.assert_not_called()


@patch(
    "app.services.agent_service.agent_telephony_service.provision_application",
    new_callable=AsyncMock,
    return_value=_telephony_attachment("vobiz"),
)
def test_telephony_create_provisions_vobiz(provision_mock: AsyncMock) -> None:
    async def _real_create(org_id, created_by_email, payload):
        attachment = await provision_mock(org_id, payload.telephony_provider, "agent-x")
        from app.services.agent_config_validation import validate_agent_config

        validated = validate_agent_config(payload.config)
        doc = {
            "agent_id": "agent-1",
            "org_id": org_id,
            "name": payload.name,
            "status": "active",
            "agent_category": payload.agent_category,
            "created_by": created_by_email,
            "linked_phone_number": None,
            "telephony": attachment,
            "config": validated.model_dump(mode="python"),
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        return doc

    with patch("app.routers.agents.agent_service.create_agent", side_effect=_real_create):
        client = _make_client()
        response = client.post(
            "/api/v1/agents",
            json={
                "name": "Tel Agent",
                "agent_category": "telephony",
                "telephony_provider": "vobiz",
                "config": _valid_config(),
            },
        )
    assert response.status_code == 201
    body = response.json()
    assert body["telephony"]["provider"] == "vobiz"
    assert body["telephony"]["application_id"] == "app-123"
    provision_mock.assert_awaited_once()


@patch(
    "app.services.agent_service.agent_telephony_service.provision_application",
    new_callable=AsyncMock,
    side_effect=AgentTelephonyError("missing auth"),
)
def test_telephony_create_auth_failure(provision_mock: AsyncMock) -> None:
    client = _make_client()
    response = client.post(
        "/api/v1/agents",
        json={
            "name": "Tel Agent",
            "agent_category": "telephony",
            "telephony_provider": "vobiz",
            "config": _valid_config(),
        },
    )
    assert response.status_code == 422
    assert "missing auth" in response.json()["detail"]
    provision_mock.assert_awaited_once()


def test_telephony_create_requires_provider() -> None:
    with patch("app.routers.agents.agent_service.create_agent", side_effect=_create):
        client = _make_client()
        response = client.post(
            "/api/v1/agents",
            json={
                "name": "Tel Agent",
                "agent_category": "telephony",
                "config": _valid_config(),
            },
        )
    assert response.status_code == 422


@patch(
    "app.services.agent_service.agent_telephony_service.delete_application",
    new_callable=AsyncMock,
)
def test_delete_telephony_agent_calls_provider(delete_mock: AsyncMock) -> None:
    async def _delete_with_telephony(org_id, agent_id):
        doc = _STORE.get((org_id, agent_id))
        if doc and doc.get("telephony"):
            await delete_mock(org_id, doc["telephony"])
        await _delete(org_id, agent_id)

    _STORE[("org-1", "agent-1")] = {
        "agent_id": "agent-1",
        "org_id": "org-1",
        "telephony": _telephony_attachment(),
    }

    with patch("app.routers.agents.agent_service.delete_agent", side_effect=_delete_with_telephony):
        client = _make_client()
        response = client.delete("/api/v1/agents/agent-1")
    assert response.status_code == 200
    delete_mock.assert_awaited_once()


@patch(
    "app.services.agent_service.agent_telephony_service.delete_application",
    new_callable=AsyncMock,
)
@patch(
    "app.services.agent_service.agent_telephony_service.provision_application",
    new_callable=AsyncMock,
    return_value=_telephony_attachment("plivo", "app-plivo"),
)
def test_patch_provider_switch(provision_mock: AsyncMock, delete_mock: AsyncMock) -> None:
    _STORE[("org-1", "agent-1")] = _full_agent_doc()

    async def _switch(org_id, agent_id, payload):
        doc = _STORE[(org_id, agent_id)]
        if doc.get("telephony"):
            await delete_mock(org_id, doc["telephony"])
        attachment = await provision_mock(org_id, "plivo", agent_id)
        updated = _full_agent_doc(telephony=attachment)
        _STORE[(org_id, agent_id)] = updated
        return updated

    with patch("app.routers.agents.agent_service.update_agent", side_effect=_switch):
        client = _make_client()
        response = client.patch(
            "/api/v1/agents/agent-1",
            json={"telephony_provider": "plivo"},
        )
    assert response.status_code == 200
    assert response.json()["telephony"]["provider"] == "plivo"
    delete_mock.assert_awaited_once()
    provision_mock.assert_awaited_once()


@patch(
    "app.services.agent_service.agent_telephony_service.delete_application",
    new_callable=AsyncMock,
)
def test_patch_telephony_to_websocket(delete_mock: AsyncMock) -> None:
    _STORE[("org-1", "agent-1")] = _full_agent_doc()

    with patch("app.routers.agents.agent_service.update_agent", side_effect=_update):
        client = _make_client()
        response = client.patch(
            "/api/v1/agents/agent-1",
            json={"agent_category": "websocket"},
        )
    assert response.status_code == 200
    assert response.json()["telephony"] is None


@patch(
    "app.services.agent_service.agent_telephony_service.provision_application",
    new_callable=AsyncMock,
    return_value=_telephony_attachment("vobiz"),
)
def test_patch_websocket_to_telephony(provision_mock: AsyncMock) -> None:
    _STORE[("org-1", "agent-1")] = _full_agent_doc(
        agent_category="websocket",
        telephony=None,
        name="WS Agent",
    )

    with patch("app.routers.agents.agent_service.update_agent", side_effect=_update):
        client = _make_client()
        response = client.patch(
            "/api/v1/agents/agent-1",
            json={"agent_category": "telephony", "telephony_provider": "vobiz"},
        )
    assert response.status_code == 200
    assert response.json()["telephony"]["provider"] == "vobiz"


@patch(
    "app.services.agent_service.agent_telephony_service.rename_application",
    new_callable=AsyncMock,
)
def test_patch_name_only_does_not_rename_telephony_app(rename_mock: AsyncMock) -> None:
    """Display name changes do not rename provider apps (app_name is agent_id)."""
    _STORE[("org-1", "agent-1")] = _full_agent_doc(name="Old Name")

    with patch("app.routers.agents.agent_service.update_agent", side_effect=_update):
        client = _make_client()
        response = client.patch(
            "/api/v1/agents/agent-1",
            json={"name": "New Name"},
        )
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"
    rename_mock.assert_not_called()
