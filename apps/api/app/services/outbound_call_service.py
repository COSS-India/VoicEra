"""Vendor-agnostic outbound call initiation with CallLogs persistence."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.services import agent_service, call_log_service, phone_number_service
from app.services.agent_service import AgentNotFoundError
from app.services.agent_telephony_service import (
    AgentTelephonyError,
    build_answer_urls,
    get_provider_dial_credentials,
)
from app.services.phone_number_service import PhoneNumberNotFoundError
from apps.telephony import initiate_outbound

logger = logging.getLogger(__name__)

_PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")


class OutboundCallError(Exception):
    """Raised when outbound call validation or dialing fails."""

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_phone(number: str, *, field: str) -> str:
    cleaned = (number or "").strip().replace(" ", "").replace("-", "")
    if not cleaned or not _PHONE_RE.match(cleaned):
        raise OutboundCallError(
            f"Invalid {field}: {number!r}. Expected E.164-style digits (7–15).",
            status_code=422,
        )
    if not cleaned.startswith("+"):
        cleaned = f"+{cleaned}"
    return cleaned


def _require_telephony_agent(agent: dict[str, Any]) -> str:
    if str(agent.get("agent_category") or "") != "telephony":
        raise OutboundCallError(
            "Outbound calls require a telephony agent",
            status_code=422,
        )
    telephony = agent.get("telephony") or {}
    provider = str(telephony.get("provider") or "").strip().lower()
    if not provider:
        raise OutboundCallError(
            "Agent has no telephony provider configured",
            status_code=422,
        )
    return provider


def _resolve_from_number(
    org_id: str,
    agent_id: str,
    agent: dict[str, Any],
    from_number_override: str | None,
) -> str:
    if from_number_override:
        return _normalize_phone(from_number_override, field="from_number")

    linked = agent.get("linked_phone_number")
    if linked:
        return _normalize_phone(str(linked), field="from_number")

    try:
        phone_doc = phone_number_service.get_by_agent(org_id, agent_id)
        return _normalize_phone(
            str(phone_doc.get("phone_number") or ""),
            field="from_number",
        )
    except PhoneNumberNotFoundError:
        pass

    raise OutboundCallError(
        "No caller ID configured for this agent. "
        "Attach a phone number or pass from_number.",
        status_code=422,
    )


def _extract_provider_call_sid(result: dict[str, Any]) -> str | None:
    for key in ("call_uuid", "request_uuid", "uuid"):
        value = result.get(key)
        if value:
            return str(value)
    raw = result.get("raw") or {}
    if isinstance(raw, dict):
        for key in ("call_uuid", "request_uuid", "uuid"):
            value = raw.get(key)
            if value:
                return str(value)
    return None


async def initiate_outbound_call(
    org_id: str,
    agent_id: str,
    to_number: str,
    *,
    from_number: str | None = None,
    custom_variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate agent, create CallLog, and place an outbound call."""
    try:
        agent = agent_service.get_agent(org_id, agent_id)
    except AgentNotFoundError as exc:
        raise OutboundCallError(str(exc), status_code=404) from exc

    provider = _require_telephony_agent(agent)
    normalized_to = _normalize_phone(to_number, field="to_number")
    normalized_from = _resolve_from_number(org_id, agent_id, agent, from_number)
    variables = dict(custom_variables or {})

    call_id = str(uuid.uuid4())
    now = _now_iso()

    call_doc: dict[str, Any] = {
        "call_id": call_id,
        "provider_call_sid": None,
        "org_id": org_id,
        "agent_id": agent_id,
        "agent_name": agent.get("name"),
        "call_type": "outbound",
        "status": "initiated",
        "call_response": "pending",
        "from_number": normalized_from,
        "to_number": normalized_to,
        "telephony_provider": provider,
        "custom_variables": variables,
        "created_at": now,
        "updated_at": now,
        "start_time_utc": now,
        "end_time_utc": None,
        "duration": None,
        "recording_url": None,
        "transcript_url": None,
        "error_message": None,
    }
    call_log_service.create_call_log(call_doc)

    answer_url, hangup_url = build_answer_urls(org_id, agent_id, call_id=call_id)

    try:
        credentials = get_provider_dial_credentials(org_id, provider)
    except AgentTelephonyError as exc:
        call_log_service.update_call_log(
            call_id,
            {"status": "failed", "call_response": "failed", "error_message": exc.message},
        )
        raise OutboundCallError(exc.message, status_code=exc.status_code) from exc

    try:
        result = await initiate_outbound(
            provider,
            auth_id=credentials["auth_id"],
            auth_token=credentials["auth_token"],
            base_url=credentials["base_url"],
            from_number=normalized_from,
            to_number=normalized_to,
            answer_url=answer_url,
            hangup_url=hangup_url,
        )
    except ValueError as exc:
        message = str(exc)
        call_log_service.update_call_log(
            call_id,
            {"status": "failed", "call_response": "failed", "error_message": message},
        )
        raise OutboundCallError(message, status_code=502) from exc
    except Exception as exc:
        message = str(exc) or "Telephony dial failed"
        call_log_service.update_call_log(
            call_id,
            {"status": "failed", "call_response": "failed", "error_message": message},
        )
        raise OutboundCallError(message, status_code=502) from exc

    if result.get("status") != "success":
        message = str(result.get("message") or "Telephony dial failed")
        call_log_service.update_call_log(
            call_id,
            {"status": "failed", "call_response": "failed", "error_message": message},
        )
        raise OutboundCallError(message, status_code=502)

    provider_call_sid = _extract_provider_call_sid(result)
    updated = call_log_service.update_call_log(
        call_id,
        {
            "status": "ringing",
            "provider_call_sid": provider_call_sid,
        },
    )

    return {
        "call_id": call_id,
        "status": updated.get("status", "ringing"),
        "provider_call_sid": provider_call_sid,
        "from_number": normalized_from,
        "to_number": normalized_to,
        "agent_id": agent_id,
        "custom_variables": variables,
    }
