"""Inbound call registration in CallLogs."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.services import agent_service, call_log_service
from app.services.agent_service import AgentNotFoundError

logger = logging.getLogger(__name__)


class InboundCallError(Exception):
    """Raised when inbound call registration fails."""

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_provider_call_sid(provider_call_sid: str) -> str:
    normalized = (provider_call_sid or "").strip()
    if not normalized:
        raise InboundCallError("provider_call_sid is required", status_code=422)
    return normalized


def _telephony_provider(agent: dict[str, Any]) -> str:
    telephony = agent.get("telephony") or {}
    provider = str(telephony.get("provider") or "").strip().lower()
    if not provider:
        raise InboundCallError(
            "Agent has no telephony provider configured",
            status_code=422,
        )
    return provider


def register_inbound_call(
    org_id: str,
    agent_id: str,
    *,
    provider_call_sid: str,
    from_number: str,
    to_number: str,
    telephony_provider: str | None = None,
) -> dict[str, Any]:
    """Create or return an existing inbound CallLog for a provider call SID."""
    try:
        agent = agent_service.get_agent(org_id, agent_id)
    except AgentNotFoundError as exc:
        raise InboundCallError(str(exc), status_code=404) from exc

    sid = _require_provider_call_sid(provider_call_sid)
    resolved_from = from_number or "unknown"
    resolved_to = to_number or "unknown"
    if resolved_to == "unknown":
        linked = str(agent.get("linked_phone_number") or "").strip()
        if linked:
            resolved_to = linked

    existing = call_log_service.get_call_log_by_provider_sid(org_id, sid)
    if existing:
        logger.info(
            "Inbound call already registered call_id=%s provider_call_sid=%s",
            existing.get("call_id"),
            sid,
        )
        patch: dict[str, str] = {}
        if resolved_from != "unknown" and (
            (existing.get("from_number") or "unknown") == "unknown"
        ):
            patch["from_number"] = resolved_from
        if resolved_to != "unknown" and (
            (existing.get("to_number") or "unknown") == "unknown"
        ):
            patch["to_number"] = resolved_to
        if patch:
            existing = call_log_service.update_call_log(str(existing["call_id"]), patch)
        return _to_register_response(existing)

    provider = telephony_provider or _telephony_provider(agent)
    now = _now_iso()
    call_id = str(uuid.uuid4())

    call_doc: dict[str, Any] = {
        "call_id": call_id,
        "provider_call_sid": sid,
        "org_id": org_id,
        "agent_id": agent_id,
        "agent_name": agent.get("name"),
        "call_type": "inbound",
        "status": "in_progress",
        "call_response": "pending",
        "from_number": resolved_from,
        "to_number": resolved_to,
        "telephony_provider": provider,
        "custom_variables": {},
        "created_at": now,
        "updated_at": now,
        "start_time_utc": now,
        "end_time_utc": None,
        "duration": None,
        "recording_url": None,
        "transcript_url": None,
        "error_message": None,
    }
    created = call_log_service.create_call_log(call_doc)
    return _to_register_response(created)


def _to_register_response(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "call_id": doc["call_id"],
        "status": doc.get("status", "in_progress"),
        "provider_call_sid": doc.get("provider_call_sid"),
        "call_type": doc.get("call_type", "inbound"),
        "from_number": doc.get("from_number", "unknown"),
        "to_number": doc.get("to_number", "unknown"),
        "agent_id": doc.get("agent_id"),
    }
