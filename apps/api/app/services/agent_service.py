"""CRUD for org-scoped Agents documents."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.database import get_database
from app.models.schemas import (
    AgentConfigPayload,
    AgentCreateRequest,
    AgentUpdateRequest,
)
from app.services.agent_config_validation import (
    AgentConfigValidationError,
    validate_agent_config,
)
from app.services import agent_telephony_service, phone_number_service
from app.services.agent_telephony_service import AgentTelephonyError
from app.utils.mongo_utils import prepare_mongo_response, prepare_mongo_response_list

logger = logging.getLogger(__name__)

COLLECTION = "Agents"


class AgentConflictError(Exception):
    """Raised when an agent name already exists in the organisation."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Agent name already exists: {name}")


class AgentNotFoundError(Exception):
    """Raised when an agent is missing for the organisation."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(f"Agent not found: {agent_id}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_response(doc: dict[str, Any]) -> dict[str, Any]:
    prepared = prepare_mongo_response(doc) or {}
    prepared.pop("_id", None)
    return prepared


def _is_telephony_category(category: str | None) -> bool:
    return (category or "").strip() == "telephony"


def _validate_create_telephony_fields(payload: AgentCreateRequest) -> str | None:
    if _is_telephony_category(payload.agent_category):
        if not payload.telephony_provider:
            return "telephony_provider is required when agent_category is telephony"
        if payload.telephony_provider not in agent_telephony_service.supported_providers():
            return f"Unsupported telephony provider: {payload.telephony_provider}"
        return None
    if payload.telephony_provider:
        return "telephony_provider must not be set when agent_category is websocket"
    return None


def _merge_config(
    existing: dict[str, Any],
    incoming: AgentConfigPayload,
    *,
    org_id: str,
) -> AgentConfigPayload:
    merged = dict(existing)
    incoming_data = incoming.model_dump(mode="python")
    for key, value in incoming_data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return validate_agent_config(
        AgentConfigPayload.model_validate(merged),
        org_id=org_id,
    )


def _effective_category(
    existing: dict[str, Any],
    payload: AgentUpdateRequest,
) -> str:
    if payload.agent_category is not None:
        return payload.agent_category
    return str(existing.get("agent_category") or "")


def _effective_provider(
    existing: dict[str, Any],
    payload: AgentUpdateRequest,
    category: str,
) -> str | None:
    if payload.telephony_provider is not None:
        return payload.telephony_provider
    if not _is_telephony_category(category):
        return None
    telephony = existing.get("telephony") or {}
    provider = telephony.get("provider")
    return str(provider) if provider else None


def _validate_update_telephony_fields(
    category: str,
    provider: str | None,
    payload: AgentUpdateRequest,
) -> None:
    if _is_telephony_category(category) and not provider:
        raise AgentConfigValidationError(
            "telephony_provider is required when agent_category is telephony"
        )
    if (
        _is_telephony_category(category)
        and provider
        and provider not in agent_telephony_service.supported_providers()
    ):
        raise AgentConfigValidationError(
            f"Unsupported telephony provider: {provider}"
        )
    if not _is_telephony_category(category) and payload.telephony_provider:
        raise AgentConfigValidationError(
            "telephony_provider must not be set when agent_category is websocket"
        )


async def create_agent(
    org_id: str,
    created_by_email: str,
    payload: AgentCreateRequest,
) -> dict[str, Any]:
    """Insert a new agent; returns the stored document."""
    name = payload.name.strip()
    if not name:
        raise AgentConfigValidationError("name is required")

    telephony_error = _validate_create_telephony_fields(payload)
    if telephony_error:
        raise AgentConfigValidationError(telephony_error)

    validated_config: AgentConfigPayload = validate_agent_config(
        payload.config,
        org_id=org_id,
    )
    now = _now_iso()
    agent_id = str(uuid.uuid4())

    telephony_attachment: dict[str, Any] | None = None
    if _is_telephony_category(payload.agent_category):
        assert payload.telephony_provider is not None
        telephony_attachment = await agent_telephony_service.provision_application(
            org_id,
            payload.telephony_provider,
            agent_id,
        )

    doc: dict[str, Any] = {
        "agent_id": agent_id,
        "org_id": org_id,
        "name": name,
        "status": "active",
        "archived": False,
        "agent_category": payload.agent_category,
        "created_by": created_by_email,
        "linked_phone_number": None,
        "telephony": telephony_attachment,
        "config": validated_config.model_dump(mode="python"),
        "created_at": now,
        "updated_at": now,
    }

    collection = get_database()[COLLECTION]
    try:
        collection.insert_one(doc)
    except DuplicateKeyError as exc:
        if telephony_attachment:
            await agent_telephony_service.delete_application(org_id, telephony_attachment)
        raise AgentConflictError(name) from exc
    except Exception:
        if telephony_attachment:
            await agent_telephony_service.delete_application(org_id, telephony_attachment)
        raise

    logger.info(
        "Agent created org=%s agent_id=%s created_by=%s",
        org_id,
        agent_id,
        created_by_email,
    )
    return _to_response(doc)


def get_agent(org_id: str, agent_id: str) -> dict[str, Any]:
    """Fetch one agent in ``org_id`` or raise AgentNotFoundError."""
    doc = get_database()[COLLECTION].find_one(
        {"org_id": org_id, "agent_id": agent_id}
    )
    if not doc:
        raise AgentNotFoundError(agent_id)
    return _to_response(doc)


def list_agents(org_id: str) -> list[dict[str, Any]]:
    """List all agents for ``org_id``, newest first."""
    cursor = (
        get_database()[COLLECTION]
        .find({"org_id": org_id})
        .sort("created_at", -1)
    )
    return prepare_mongo_response_list(
        [{k: v for k, v in doc.items() if k != "_id"} for doc in cursor]
    )


async def update_agent(
    org_id: str,
    agent_id: str,
    payload: AgentUpdateRequest,
) -> dict[str, Any]:
    """Partially update an agent and reconcile telephony application lifecycle."""
    collection = get_database()[COLLECTION]
    existing = collection.find_one({"org_id": org_id, "agent_id": agent_id})
    if not existing:
        raise AgentNotFoundError(agent_id)

    category = _effective_category(existing, payload)
    provider = _effective_provider(existing, payload, category)
    _validate_update_telephony_fields(category, provider, payload)

    old_category = str(existing.get("agent_category") or "")
    old_telephony = existing.get("telephony")
    old_provider = (
        str(old_telephony.get("provider"))
        if isinstance(old_telephony, dict) and old_telephony.get("provider")
        else None
    )

    new_name = payload.name.strip() if payload.name is not None else None
    if new_name is not None and not new_name:
        raise AgentConfigValidationError("name is required")

    name = new_name if new_name is not None else str(existing.get("name") or "")

    validated_config: AgentConfigPayload
    if payload.config is not None:
        validated_config = _merge_config(
            existing.get("config") or {},
            payload.config,
            org_id=org_id,
        )
    else:
        validated_config = validate_agent_config(
            AgentConfigPayload.model_validate(existing.get("config") or {}),
            org_id=org_id,
        )

    telephony_changed = (
        old_category != category
        or (_is_telephony_category(category) and old_provider != provider)
    )
    telephony_attachment: dict[str, Any] | None = (
        dict(old_telephony) if isinstance(old_telephony, dict) else None
    )

    if telephony_changed:
        await phone_number_service.detach_from_agent(org_id, agent_id)
        if isinstance(old_telephony, dict):
            await agent_telephony_service.delete_application(org_id, old_telephony)
        telephony_attachment = None
        if _is_telephony_category(category):
            assert provider is not None
            telephony_attachment = await agent_telephony_service.provision_application(
                org_id,
                provider,
                agent_id,
            )

    update_doc: dict[str, Any] = {
        "name": name,
        "agent_category": category,
        "config": validated_config.model_dump(mode="python"),
        "telephony": telephony_attachment,
        "updated_at": _now_iso(),
    }
    if telephony_changed:
        update_doc["linked_phone_number"] = None
    if payload.archived is not None:
        update_doc["archived"] = payload.archived

    try:
        collection.update_one(
            {"org_id": org_id, "agent_id": agent_id},
            {"$set": update_doc},
        )
    except DuplicateKeyError as exc:
        if telephony_changed and telephony_attachment:
            await agent_telephony_service.delete_application(org_id, telephony_attachment)
        raise AgentConflictError(name) from exc
    except Exception:
        if telephony_changed and telephony_attachment:
            await agent_telephony_service.delete_application(org_id, telephony_attachment)
        raise

    updated = collection.find_one({"org_id": org_id, "agent_id": agent_id})
    assert updated is not None
    logger.info("Agent updated org=%s agent_id=%s", org_id, agent_id)
    return _to_response(updated)


async def delete_agent(org_id: str, agent_id: str) -> None:
    """Hard-delete an agent in ``org_id`` or raise AgentNotFoundError."""
    collection = get_database()[COLLECTION]
    existing = collection.find_one({"org_id": org_id, "agent_id": agent_id})
    if not existing:
        raise AgentNotFoundError(agent_id)

    await phone_number_service.detach_from_agent(org_id, agent_id)

    telephony = existing.get("telephony")
    if isinstance(telephony, dict):
        await agent_telephony_service.delete_application(org_id, telephony)

    result = collection.delete_one({"org_id": org_id, "agent_id": agent_id})
    if result.deleted_count == 0:
        raise AgentNotFoundError(agent_id)
    logger.info("Agent deleted org=%s agent_id=%s", org_id, agent_id)
