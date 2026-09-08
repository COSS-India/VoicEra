"""Org phone-number inventory and agent attach/detach (with provider sync)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.database import get_database
from app.services import agent_telephony_service
from app.services.agent_telephony_service import AgentTelephonyError
from app.utils.mongo_utils import prepare_mongo_response, prepare_mongo_response_list

logger = logging.getLogger(__name__)

COLLECTION = "PhoneNumbers"
AGENTS_COLLECTION = "Agents"


class PhoneNumberError(Exception):
    """Raised for phone-number business-rule failures."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class PhoneNumberNotFoundError(PhoneNumberError):
    """Phone number document missing."""

    def __init__(self, message: str = "Phone number not found") -> None:
        super().__init__(message, status_code=404)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_response(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    prepared = prepare_mongo_response(doc) or {}
    prepared.pop("_id", None)
    return prepared


def _last_link_fields(
    action: str,
    agent_id: str | None,
    member_email: str | None,
    at: str,
) -> dict[str, str]:
    if not member_email:
        return {}
    return {
        "last_link_action": action,
        "last_link_agent_id": agent_id or "",
        "last_link_by_email": member_email,
        "last_link_at": at,
    }


def list_by_org(org_id: str) -> list[dict[str, Any]]:
    """Return all phone numbers for ``org_id``."""
    cursor = get_database()[COLLECTION].find({"org_id": org_id}).sort("created_at", -1)
    return prepare_mongo_response_list(
        [{k: v for k, v in doc.items() if k != "_id"} for doc in cursor]
    )


def get_by_agent(org_id: str, agent_id: str) -> dict[str, Any]:
    """Return the phone number attached to ``agent_id`` in ``org_id``."""
    doc = get_database()[COLLECTION].find_one(
        {"org_id": org_id, "agent_id": agent_id}
    )
    if not doc:
        raise PhoneNumberNotFoundError("No phone number attached to this agent")
    return _to_response(doc) or {}


def get_agent_by_phone(phone_number: str) -> dict[str, Any]:
    """Resolve an agent by ``linked_phone_number`` (voice / inbound routing)."""
    doc = get_database()[AGENTS_COLLECTION].find_one(
        {"linked_phone_number": phone_number}
    )
    if not doc:
        raise PhoneNumberNotFoundError("No agent found for this phone number")
    prepared = prepare_mongo_response(doc) or {}
    prepared.pop("_id", None)
    return prepared


def _load_agent(org_id: str, agent_id: str) -> dict[str, Any]:
    doc = get_database()[AGENTS_COLLECTION].find_one(
        {"org_id": org_id, "agent_id": agent_id}
    )
    if not doc:
        raise PhoneNumberNotFoundError(f"Agent not found: {agent_id}")
    return doc


def _clear_agent_linked_number(org_id: str, agent_id: str, at: str) -> None:
    get_database()[AGENTS_COLLECTION].update_one(
        {"org_id": org_id, "agent_id": agent_id},
        {
            "$set": {
                "linked_phone_number": None,
                "updated_at": at,
            }
        },
    )


def _set_agent_linked_number(
    org_id: str,
    agent_id: str,
    phone_number: str,
    at: str,
) -> None:
    get_database()[AGENTS_COLLECTION].update_one(
        {"org_id": org_id, "agent_id": agent_id},
        {
            "$set": {
                "linked_phone_number": phone_number,
                "updated_at": at,
            }
        },
    )


async def _unlink_previous_owner_if_needed(
    existing: dict[str, Any] | None,
    org_id: str,
    phone_number: str,
    new_agent_id: str | None,
) -> None:
    """If number moves to a different agent (or re-attach), clear prior agent link."""
    if not existing:
        return
    prev_agent_id = existing.get("agent_id")
    if not prev_agent_id:
        return
    if new_agent_id and prev_agent_id == new_agent_id:
        return

    prev_provider = str(existing.get("provider") or "").strip()
    if prev_provider:
        try:
            await agent_telephony_service.unlink_number(
                org_id, prev_provider, phone_number
            )
        except AgentTelephonyError as exc:
            logger.warning(
                "Failed to unlink previous owner for %s: %s",
                phone_number,
                exc.message,
            )

    at = _now_iso()
    _clear_agent_linked_number(org_id, str(prev_agent_id), at)


async def attach(
    org_id: str,
    phone_number: str,
    provider: str,
    *,
    agent_id: str | None = None,
    member_email: str | None = None,
) -> dict[str, Any]:
    """Upsert inventory; optionally link to agent + provider application."""
    phone_number = phone_number.strip()
    provider = provider.strip().lower()
    if not phone_number:
        raise PhoneNumberError("phone_number is required")
    if provider not in agent_telephony_service.supported_providers():
        raise PhoneNumberError(f"Unsupported telephony provider: {provider}")

    phones = get_database()[COLLECTION]
    existing = phones.find_one({"phone_number": phone_number})
    if existing and existing.get("org_id") and existing.get("org_id") != org_id:
        raise PhoneNumberError(
            "Phone number is already registered to another organisation",
            status_code=409,
        )

    application_id: str | None = None
    if agent_id:
        agent = _load_agent(org_id, agent_id)
        if str(agent.get("agent_category") or "") != "telephony":
            raise PhoneNumberError(
                "Phone numbers can only be attached to telephony agents"
            )
        telephony = agent.get("telephony")
        if not isinstance(telephony, dict):
            raise PhoneNumberError(
                "Agent has no telephony application; cannot attach phone number"
            )
        agent_provider = str(telephony.get("provider") or "").strip()
        if agent_provider != provider:
            raise PhoneNumberError(
                f"Provider '{provider}' does not match agent telephony provider "
                f"'{agent_provider}'"
            )
        application_id = str(telephony.get("application_id") or "").strip() or None
        if not application_id:
            raise PhoneNumberError(
                "Agent has no telephony application_id; cannot attach phone number"
            )

        other = phones.find_one(
            {
                "org_id": org_id,
                "agent_id": agent_id,
                "phone_number": {"$ne": phone_number},
            }
        )
        if other:
            raise PhoneNumberError(
                "Agent already has a phone number attached; detach it first",
                status_code=409,
            )

        await _unlink_previous_owner_if_needed(
            existing, org_id, phone_number, agent_id
        )
        await agent_telephony_service.link_number(
            org_id, provider, phone_number, application_id
        )
    else:
        await _unlink_previous_owner_if_needed(existing, org_id, phone_number, None)

    now = _now_iso()
    audit = _last_link_fields(
        "attached" if agent_id else "imported",
        agent_id,
        member_email,
        now,
    )

    if existing:
        update_doc: dict[str, Any] = {
            "provider": provider,
            "org_id": org_id,
            "updated_at": now,
            **audit,
        }
        if agent_id:
            update_doc["agent_id"] = agent_id
            phones.update_one(
                {"phone_number": phone_number},
                {"$set": update_doc},
            )
        else:
            phones.update_one(
                {"phone_number": phone_number},
                {"$set": update_doc, "$unset": {"agent_id": ""}},
            )
    else:
        phone_doc: dict[str, Any] = {
            "phone_number": phone_number,
            "provider": provider,
            "org_id": org_id,
            "created_at": now,
            "updated_at": now,
            **audit,
        }
        if agent_id:
            phone_doc["agent_id"] = agent_id
        phones.insert_one(phone_doc)

    if agent_id:
        # Clear any stale linked_phone_number on this agent pointing elsewhere.
        prev_on_agent = get_database()[AGENTS_COLLECTION].find_one(
            {
                "org_id": org_id,
                "agent_id": agent_id,
                "linked_phone_number": {"$nin": [None, phone_number]},
            }
        )
        if prev_on_agent and prev_on_agent.get("linked_phone_number"):
            logger.info(
                "Replacing linked_phone_number on agent %s",
                agent_id,
            )
        _set_agent_linked_number(org_id, agent_id, phone_number, now)

    logger.info(
        "Phone number attached org=%s phone=%s agent_id=%s",
        org_id,
        phone_number,
        agent_id,
    )
    return {
        "status": "success",
        "message": (
            "Phone number attached successfully"
            if agent_id
            else "Phone number added to inventory successfully"
        ),
    }


async def detach(
    org_id: str,
    phone_number: str,
    *,
    member_email: str | None = None,
    unlink_provider: bool = True,
) -> dict[str, Any]:
    """Unlink from provider, clear agent association; keep inventory row."""
    phone_number = phone_number.strip()
    phones = get_database()[COLLECTION]
    existing = phones.find_one({"phone_number": phone_number})
    if not existing:
        raise PhoneNumberNotFoundError()
    if existing.get("org_id") != org_id:
        raise PhoneNumberError(
            "Not authorized to detach this phone number",
            status_code=403,
        )
    agent_id = existing.get("agent_id")
    if not agent_id:
        raise PhoneNumberError("Phone number is not attached to any agent")

    provider = str(existing.get("provider") or "").strip()
    if unlink_provider and provider:
        await agent_telephony_service.unlink_number(org_id, provider, phone_number)

    now = _now_iso()
    phones.update_one(
        {"phone_number": phone_number},
        {
            "$unset": {"agent_id": ""},
            "$set": {
                "updated_at": now,
                **_last_link_fields("detached", str(agent_id), member_email, now),
            },
        },
    )
    _clear_agent_linked_number(org_id, str(agent_id), now)

    logger.info(
        "Phone number detached org=%s phone=%s agent_id=%s",
        org_id,
        phone_number,
        agent_id,
    )
    return {"status": "success", "message": "Phone number detached successfully"}


async def detach_from_agent(
    org_id: str,
    agent_id: str,
    *,
    member_email: str | None = None,
    unlink_provider: bool = True,
) -> None:
    """Best-effort detach when an agent is deleted or telephony changes."""
    doc = get_database()[COLLECTION].find_one(
        {"org_id": org_id, "agent_id": agent_id}
    )
    phone = str(doc["phone_number"]) if doc else None
    if not phone:
        agent = get_database()[AGENTS_COLLECTION].find_one(
            {"org_id": org_id, "agent_id": agent_id}
        )
        linked = (agent or {}).get("linked_phone_number")
        phone = str(linked) if linked else None

    if not phone:
        return

    try:
        await detach(
            org_id,
            phone,
            member_email=member_email,
            unlink_provider=unlink_provider,
        )
    except (PhoneNumberError, AgentTelephonyError) as exc:
        message = getattr(exc, "message", str(exc))
        logger.warning(
            "Could not detach phone %s for agent %s: %s",
            phone,
            agent_id,
            message,
        )
        now = _now_iso()
        get_database()[COLLECTION].update_one(
            {"org_id": org_id, "phone_number": phone},
            {
                "$unset": {"agent_id": ""},
                "$set": {"updated_at": now},
            },
        )
        _clear_agent_linked_number(org_id, agent_id, now)
