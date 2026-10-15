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
    load_telephony_client,
)
from app.services.phone_number_service import PhoneNumberNotFoundError
from apps.telephony import initiate_outbound
from apps.telephony.phone_format import format_e164_for_call_log
from apps.telephony.registry import defers_call_log_to_stream
from apps.telephony.results import provider_call_sid_from_result

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
    cleaned = format_e164_for_call_log(number or "")
    if not cleaned or cleaned.lower() == "unknown":
        raise OutboundCallError(
            f"Invalid {field}: {number!r}. Expected E.164-style digits (7–15).",
            status_code=422,
        )
    if not _PHONE_RE.match(cleaned):
        raise OutboundCallError(
            f"Invalid {field}: {number!r}. Expected E.164-style digits (7–15).",
            status_code=422,
        )
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
    *,
    provider: str | None = None,
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

    # Optional client capability (e.g. auth-configured DNIs) when no linked number.
    normalized_provider = (provider or "").strip().lower()
    if not normalized_provider:
        telephony = agent.get("telephony") or {}
        normalized_provider = str(telephony.get("provider") or "").strip().lower()
    if normalized_provider:
        try:
            client = load_telephony_client(org_id, normalized_provider)
        except AgentTelephonyError:
            client = None
        else:
            fallback = getattr(client, "default_from_number", None)
            if callable(fallback):
                auth_dni = fallback()
                if auth_dni:
                    return _normalize_phone(str(auth_dni), field="from_number")

    raise OutboundCallError(
        "No caller ID configured for this agent. "
        "Attach a phone number or pass from_number.",
        status_code=422,
    )

def _mark_call_failed(call_id: str | None, message: str) -> None:
    if not call_id:
        return
    call_log_service.update_call_log(
        call_id,
        {"status": "failed", "call_response": "failed", "error_message": message},
    )


async def initiate_outbound_call(
    org_id: str,
    agent_id: str,
    to_number: str,
    *,
    from_number: str | None = None,
    custom_variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate agent and place an outbound call.

    Most providers create a CallLog at dial time. VI defers CallLog creation
    until the media WebSocket connects (see :func:`register_outbound_call`).
    """
    try:
        agent = agent_service.get_agent(org_id, agent_id)
    except AgentNotFoundError as exc:
        raise OutboundCallError(str(exc), status_code=404) from exc

    provider = _require_telephony_agent(agent)
    normalized_to = _normalize_phone(to_number, field="to_number")
    normalized_from = _resolve_from_number(
        org_id, agent_id, agent, from_number, provider=provider
    )
    variables = dict(custom_variables or {})
    defer_log = defers_call_log_to_stream(provider)

    call_id: str | None = None
    if not defer_log:
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
        credentials = dict(get_provider_dial_credentials(org_id, provider))
    except AgentTelephonyError as exc:
        _mark_call_failed(call_id, exc.message)
        raise OutboundCallError(exc.message, status_code=exc.status_code) from exc

    auth_id = str(credentials.pop("auth_id", "") or "")
    auth_token = str(credentials.pop("auth_token", "") or "")
    base_url = str(credentials.pop("base_url", "") or "")

    try:
        result = await initiate_outbound(
            provider,
            auth_id=auth_id,
            auth_token=auth_token,
            base_url=base_url,
            from_number=normalized_from,
            to_number=normalized_to,
            answer_url=answer_url,
            hangup_url=hangup_url,
            **credentials,
        )
    except ValueError as exc:
        message = str(exc)
        _mark_call_failed(call_id, message)
        raise OutboundCallError(message, status_code=502) from exc
    except Exception as exc:
        message = str(exc) or "Telephony dial failed"
        _mark_call_failed(call_id, message)
        raise OutboundCallError(message, status_code=502) from exc

    if result.get("status") != "success":
        message = str(result.get("message") or "Telephony dial failed")
        _mark_call_failed(call_id, message)
        raise OutboundCallError(message, status_code=502)

    provider_call_sid = provider_call_sid_from_result(result)
    dial_dni = result.get("dni")
    if dial_dni is not None and str(dial_dni).strip():
        normalized_from = format_e164_for_call_log(str(dial_dni))

    status = "ringing"
    if call_id:
        patch: dict[str, Any] = {
            "status": status,
            "provider_call_sid": provider_call_sid,
        }
        if dial_dni is not None and str(dial_dni).strip():
            patch["from_number"] = normalized_from
        updated = call_log_service.update_call_log(call_id, patch)
        status = str(updated.get("status") or status)

    return {
        "call_id": call_id,
        "status": status,
        "provider_call_sid": provider_call_sid,
        "from_number": normalized_from,
        "to_number": normalized_to,
        "agent_id": agent_id,
        "custom_variables": variables,
    }


def _require_provider_call_sid(provider_call_sid: str) -> str:
    normalized = (provider_call_sid or "").strip()
    if not normalized:
        raise OutboundCallError("provider_call_sid is required", status_code=422)
    return normalized


def _resolve_outbound_register_numbers(
    from_number: str,
    to_number: str,
) -> tuple[str, str]:
    """Canonicalize outbound CLI/DNI for CallLog storage (E.164)."""
    resolved_from = format_e164_for_call_log(from_number or "unknown")
    resolved_to = format_e164_for_call_log(to_number or "unknown")
    return resolved_from, resolved_to


def _to_register_response(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "call_id": doc["call_id"],
        "status": doc.get("status", "in_progress"),
        "provider_call_sid": doc.get("provider_call_sid"),
        "call_type": doc.get("call_type", "outbound"),
        "from_number": doc.get("from_number", "unknown"),
        "to_number": doc.get("to_number", "unknown"),
        "agent_id": doc.get("agent_id"),
    }


def register_outbound_call(
    org_id: str,
    agent_id: str,
    *,
    provider_call_sid: str,
    from_number: str,
    to_number: str = "unknown",
    telephony_provider: str | None = None,
) -> dict[str, Any]:
    """Create or return an existing outbound CallLog for a provider call SID.

    Used when the voice runtime stream starts for an outbound VI call
    (CLI == DNI). Idempotent on ``provider_call_sid``.
    """
    try:
        agent = agent_service.get_agent(org_id, agent_id)
    except AgentNotFoundError as exc:
        raise OutboundCallError(str(exc), status_code=404) from exc

    sid = _require_provider_call_sid(provider_call_sid)
    resolved_from, resolved_to = _resolve_outbound_register_numbers(
        from_number,
        to_number,
    )

    existing = call_log_service.get_call_log_by_provider_sid(org_id, sid)
    if existing:
        logger.info(
            "Outbound call already registered call_id=%s provider_call_sid=%s",
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

    if telephony_provider:
        provider = telephony_provider.strip().lower()
    else:
        provider = _require_telephony_agent(agent)

    now = _now_iso()
    call_id = str(uuid.uuid4())

    call_doc: dict[str, Any] = {
        "call_id": call_id,
        "provider_call_sid": sid,
        "org_id": org_id,
        "agent_id": agent_id,
        "agent_name": agent.get("name"),
        "call_type": "outbound",
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
