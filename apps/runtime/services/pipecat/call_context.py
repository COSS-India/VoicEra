"""Per-call telephony context wired into LLM processors (opt-in hooks)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from loguru import logger

from apps.telephony.phone_format import format_e164_for_call_log

_PLACEHOLDER_PHONES = frozenset({"", "unknown", "na", "n/a"})


@dataclass(frozen=True, slots=True)
class CallPhones:
    from_number: str
    to_number: str
    call_type: str | None


def phones_from_call_log(call_log: Mapping[str, Any] | None) -> CallPhones | None:
    if not call_log:
        return None
    from_n = format_e164_for_call_log(str(call_log.get("from_number") or ""))
    to_n = format_e164_for_call_log(str(call_log.get("to_number") or ""))
    call_type = call_log.get("call_type")
    ctype = str(call_type).strip() if call_type is not None else None
    if ctype == "":
        ctype = None
    return CallPhones(from_number=from_n, to_number=to_n, call_type=ctype)


def _usable_phone(number: str) -> str | None:
    value = (number or "").strip()
    if value.lower() in _PLACEHOLDER_PHONES:
        return None
    return value


def resolve_participant_phone(phones: CallPhones) -> str | None:
    """Remote party on the call (caller for inbound, callee for outbound)."""
    call_type = (phones.call_type or "inbound").strip().lower()
    if call_type == "outbound":
        return _usable_phone(phones.to_number)
    return _usable_phone(phones.from_number)


def participant_phone_from_call_log(
    call_log: Mapping[str, Any] | None,
) -> str | None:
    phones = phones_from_call_log(call_log)
    if phones is None:
        return None
    return resolve_participant_phone(phones)


async def resolve_call_log(
    org_id: str,
    call_id: str | None,
    call_log: Mapping[str, Any] | None,
    *,
    fetch_call: Callable[[str, str], Awaitable[dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    """Use ``call_log`` when provided; otherwise load by ``call_id`` for telephony sessions."""
    if call_log is not None:
        return dict(call_log)
    if not (call_id and org_id):
        return None
    if fetch_call is None:
        from apps.runtime.services.backend import BackendError, backend_client

        async def _fetch(cid: str, oid: str) -> dict[str, Any]:
            return await backend_client.get_call(cid, oid)

        fetch_call = _fetch
    try:
        return await fetch_call(call_id, org_id)
    except Exception as exc:  # noqa: BLE001 — telephony must start if CallLog fetch fails
        logger.warning(
            "Could not load call log for participant phone call_id={} org_id={}: {}",
            call_id,
            org_id,
            exc,
        )
        return None


def wire_llm_call_session(
    llm: Any,
    *,
    call_id: str | None,
    participant_phone: str | None,
    spoken_greeting: str | None = None,
) -> None:
    for member in llm.services:
        if call_id and hasattr(member, "set_call_id"):
            member.set_call_id(call_id)
        if (
            participant_phone
            and hasattr(member, "set_participant_phone")
            and getattr(member, "_use_participant_phone", False)
        ):
            member.set_participant_phone(participant_phone)
        if spoken_greeting is not None and hasattr(member, "set_spoken_greeting"):
            member.set_spoken_greeting(spoken_greeting)
