"""Agent create / list / get / delete route tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.models.schemas import AgentCreateRequest, AgentUpdateRequest
from app.routers import agents
from app.services.agent_config_validation import AgentConfigValidationError
from app.services.agent_service import AgentConflictError, AgentNotFoundError

_STORE: dict[tuple[str, str], dict[str, Any]] = {}


def _admin_user() -> dict[str, Any]:
    return {
        "email": "admin@example.com",
        "org_id": "org-1",
        "role": "admin",
    }


def _member_user() -> dict[str, Any]:
    return {
        "email": "member@example.com",
        "org_id": "org-1",
        "role": "member",
    }


def _other_org_admin() -> dict[str, Any]:
    return {
        "email": "other@example.com",
        "org_id": "org-2",
        "role": "admin",
    }


def _valid_create_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Support Agent",
        "agent_category": "websocket",
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
    body.update(overrides)
    return body


async def _create(
    org_id: str,
    created_by_email: str,
    payload: AgentCreateRequest,
) -> dict[str, Any]:
    from app.services.agent_config_validation import validate_agent_config

    name = payload.name.strip()
    if not name:
        raise AgentConfigValidationError("name is required")
    for (_org, _aid), doc in _STORE.items():
        if _org == org_id and doc["name"] == name:
            raise AgentConflictError(name)

    validated = validate_agent_config(payload.config)
    agent_id = f"agent-{len(_STORE) + 1}"
    doc = {
        "agent_id": agent_id,
        "org_id": org_id,
        "name": name,
        "status": "active",
        "agent_category": payload.agent_category,
        "created_by": created_by_email,
        "linked_phone_number": None,
        "telephony": None,
        "config": validated.model_dump(mode="python"),
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    _STORE[(org_id, agent_id)] = doc
    return dict(doc)


def _get(org_id: str, agent_id: str) -> dict[str, Any]:
    doc = _STORE.get((org_id, agent_id))
    if not doc:
        raise AgentNotFoundError(agent_id)
    return dict(doc)


def _list(org_id: str) -> list[dict[str, Any]]:
    return [
        dict(doc)
        for (o, _), doc in sorted(_STORE.items(), key=lambda item: item[1]["agent_id"])
        if o == org_id
    ]


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
    if payload.config is not None:
        from app.services.agent_config_validation import validate_agent_config

        updated["config"] = validate_agent_config(payload.config).model_dump(mode="python")
    updated["updated_at"] = "2026-01-02T00:00:00+00:00"
    _STORE[(org_id, agent_id)] = updated
    return dict(updated)


async def _delete(org_id: str, agent_id: str) -> None:
    if (org_id, agent_id) not in _STORE:
        raise AgentNotFoundError(agent_id)
    del _STORE[(org_id, agent_id)]


def _make_client(user_factory) -> TestClient:
    app = FastAPI()
    app.include_router(agents.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = user_factory
    return TestClient(app)


def setup_function() -> None:
    _STORE.clear()


@patch("app.routers.agents.agent_service.create_agent", side_effect=_create)
@patch("app.routers.agents.agent_service.get_agent", side_effect=_get)
@patch("app.routers.agents.agent_service.list_agents", side_effect=_list)
@patch("app.routers.agents.agent_service.delete_agent", side_effect=_delete)
def test_member_can_create_with_created_by(
    _delete_m, _list_m, _get_m, _create_m
):
    client = _make_client(_member_user)
    response = client.post("/api/v1/agents", json=_valid_create_body())
    assert response.status_code == 201
    body = response.json()
    assert body["created_by"] == "member@example.com"
    assert body["org_id"] == "org-1"
    assert body["telephony"] is None
    assert body["linked_phone_number"] is None
    assert body["config"]["models"]["en"]["stt_config"]["provider"] == "openai"
    assert "api_key" not in body["config"]["models"]["en"]["stt_config"]
    assert "language_models" not in body["config"]


@patch("app.routers.agents.agent_service.create_agent", side_effect=_create)
def test_vad_knobs_survive_config_validation(_create_m):
    """Unknown behaviour keys are dropped by model_dump — VAD must be declared."""
    client = _make_client(_admin_user)
    body = _valid_create_body()
    body["config"]["behaviour"] = {"vad_stop_secs": 1.0, "vad_min_volume": 0}
    response = client.post("/api/v1/agents", json=body)
    assert response.status_code == 201
    behaviour = response.json()["config"]["behaviour"]
    assert behaviour["vad_stop_secs"] == 1.0
    assert behaviour["vad_min_volume"] == 0
    assert behaviour["vad_confidence"] is None
    assert behaviour["vad_start_secs"] is None


@patch("app.routers.agents.agent_service.create_agent", side_effect=_create)
def test_create_rejects_out_of_range_vad_knobs(_create_m):
    client = _make_client(_admin_user)
    body = _valid_create_body()
    body["config"]["behaviour"] = {"vad_confidence": 1.5}
    assert client.post("/api/v1/agents", json=body).status_code == 422


@patch("app.routers.agents.agent_service.create_agent", side_effect=_create)
def test_create_rejects_secret_fields(_create_m):
    client = _make_client(_admin_user)
    body = _valid_create_body()
    body["config"]["models"]["llm_config"]["api_key"] = "sk-secret"
    response = client.post("/api/v1/agents", json=body)
    assert response.status_code == 422
    assert "secret" in response.json()["detail"].lower() or "api_key" in response.json()[
        "detail"
    ]


@patch("app.routers.agents.agent_service.create_agent", side_effect=_create)
def test_create_rejects_unknown_provider(_create_m):
    client = _make_client(_admin_user)
    body = _valid_create_body()
    body["config"]["models"]["stt_config"] = {
        "provider": "not-a-real-provider",
        "model": "x",
    }
    response = client.post("/api/v1/agents", json=body)
    assert response.status_code == 422


@patch("app.routers.agents.agent_service.create_agent", side_effect=_create)
def test_duplicate_name_conflict(_create_m):
    client = _make_client(_admin_user)
    first = client.post("/api/v1/agents", json=_valid_create_body())
    assert first.status_code == 201
    second = client.post("/api/v1/agents", json=_valid_create_body())
    assert second.status_code == 409


@patch("app.routers.agents.agent_service.create_agent", side_effect=_create)
@patch("app.routers.agents.agent_service.get_agent", side_effect=_get)
@patch("app.routers.agents.agent_service.list_agents", side_effect=_list)
def test_list_and_get_include_created_by(_list_m, _get_m, _create_m):
    client = _make_client(_member_user)
    created = client.post("/api/v1/agents", json=_valid_create_body()).json()
    listed = client.get("/api/v1/agents")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["created_by"] == "member@example.com"

    fetched = client.get(f"/api/v1/agents/{created['agent_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["agent_id"] == created["agent_id"]


@patch("app.routers.agents.agent_service.create_agent", side_effect=_create)
@patch("app.routers.agents.agent_service.get_agent", side_effect=_get)
@patch("app.routers.agents.agent_service.delete_agent", side_effect=_delete)
def test_admin_delete_and_second_delete_404(_delete_m, _get_m, _create_m):
    create_client = _make_client(_member_user)
    created = create_client.post("/api/v1/agents", json=_valid_create_body()).json()
    agent_id = created["agent_id"]

    admin = _make_client(_admin_user)
    deleted = admin.delete(f"/api/v1/agents/{agent_id}")
    assert deleted.status_code == 200

    again = admin.delete(f"/api/v1/agents/{agent_id}")
    assert again.status_code == 404


@patch("app.routers.agents.agent_service.create_agent", side_effect=_create)
@patch("app.routers.agents.agent_service.delete_agent", side_effect=_delete)
def test_member_cannot_delete(_delete_m, _create_m):
    client = _make_client(_member_user)
    created = client.post("/api/v1/agents", json=_valid_create_body()).json()
    response = client.delete(f"/api/v1/agents/{created['agent_id']}")
    assert response.status_code == 403


@patch("app.routers.agents.agent_service.create_agent", side_effect=_create)
@patch("app.routers.agents.agent_service.get_agent", side_effect=_get)
@patch("app.routers.agents.agent_service.delete_agent", side_effect=_delete)
def test_other_org_cannot_get_or_delete(_delete_m, _get_m, _create_m):
    owner = _make_client(_admin_user)
    created = owner.post("/api/v1/agents", json=_valid_create_body()).json()
    agent_id = created["agent_id"]

    other = _make_client(_other_org_admin)
    assert other.get(f"/api/v1/agents/{agent_id}").status_code == 404
    assert other.delete(f"/api/v1/agents/{agent_id}").status_code == 404


@patch("app.routers.agents.agent_service.create_agent", side_effect=_create)
@patch("app.routers.agents.agent_service.update_agent", side_effect=_update)
def test_patch_updates_agent_name(_update_m, _create_m):
    client = _make_client(_member_user)
    created = client.post("/api/v1/agents", json=_valid_create_body()).json()
    response = client.patch(
        f"/api/v1/agents/{created['agent_id']}",
        json={"name": "Renamed Agent"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed Agent"


def _merge_stack(llm_model: str) -> dict[str, Any]:
    return {
        "stt_config": {"provider": "openai", "model": "gpt-4o-transcribe"},
        "tts_config": {"provider": "openai", "model": "gpt-4o-mini-tts", "voice": "alloy"},
        "llm_config": {"provider": "openai", "model": llm_model},
    }


def _merge_payload(language: dict[str, Any], models: dict[str, Any]):
    from app.models.schemas import AgentConfigPayload

    return AgentConfigPayload.model_validate(
        {
            "prompts": {"system_prompt": "You are helpful.", "greeting_message": "Hi!"},
            "language": language,
            "models": models,
        }
    )


def test_patch_replaces_a_stored_flat_models_stack():
    """Agents saved before language-keyed models store a flat stack."""
    from app.services.agent_service import _merge_config

    stored = {
        "prompts": {"system_prompt": "Old.", "greeting_message": "Hello"},
        "language": {"primary": "en", "secondary": []},
        "models": _merge_stack("gpt-4.1"),
    }
    incoming = _merge_payload(
        {"primary": "en", "secondary": []}, {"en": _merge_stack("gpt-4.1-mini")}
    )
    merged = _merge_config(stored, incoming, org_id="org-1")
    assert merged.models["en"].llm_config["model"] == "gpt-4.1-mini"


def test_patch_drops_the_stack_of_a_removed_language():
    from app.services.agent_service import _merge_config

    stored = {
        "prompts": {"system_prompt": "Old.", "greeting_message": "Hello"},
        "language": {"primary": "en", "secondary": ["hi"]},
        "models": {"en": _merge_stack("gpt-4.1"), "hi": _merge_stack("gpt-4.1")},
    }
    incoming = _merge_payload({"primary": "en", "secondary": []}, {"en": _merge_stack("gpt-4.1")})
    merged = _merge_config(stored, incoming, org_id="org-1")
    assert set(merged.models) == {"en"}
