"""Tests for per-call LLM wiring from telephony call logs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from apps.runtime.services.pipecat.call_context import (
    CallPhones,
    participant_phone_from_call_log,
    phones_from_call_log,
    resolve_call_log,
    resolve_participant_phone,
    wire_llm_call_session,
)


def test_resolve_participant_phone_inbound() -> None:
    phones = CallPhones(
        from_number="+919876543210",
        to_number="+911234567890",
        call_type="inbound",
    )
    assert resolve_participant_phone(phones) == "+919876543210"


def test_resolve_participant_phone_outbound() -> None:
    phones = CallPhones(
        from_number="+911234567890",
        to_number="+919876543210",
        call_type="outbound",
    )
    assert resolve_participant_phone(phones) == "+919876543210"


def test_resolve_participant_phone_unknown_skipped() -> None:
    phones = CallPhones(from_number="unknown", to_number="+919876543210", call_type="inbound")
    assert resolve_participant_phone(phones) is None


def test_resolve_participant_phone_na_placeholder_skipped() -> None:
    phones = CallPhones(
        from_number="+911111111111",
        to_number="NA",
        call_type="outbound",
    )
    assert resolve_participant_phone(phones) is None


def test_participant_phone_from_call_log_inbound() -> None:
    assert (
        participant_phone_from_call_log(
            {
                "from_number": "+919876543210",
                "to_number": "+911111111111",
                "call_type": "inbound",
            }
        )
        == "+919876543210"
    )


def test_resolve_call_log_uses_inline_when_provided() -> None:
    log = {"call_id": "c1", "from_number": "+91"}

    async def _run() -> None:
        assert await resolve_call_log("org", "c1", log) == log

    asyncio.run(_run())


def test_resolve_call_log_fetches_when_missing() -> None:
    async def fetch(call_id: str, org_id: str) -> dict:
        assert call_id == "c1"
        assert org_id == "org-1"
        return {
            "call_id": call_id,
            "from_number": "9876543210",
            "to_number": "unknown",
            "call_type": "inbound",
        }

    async def _run() -> None:
        loaded = await resolve_call_log("org-1", "c1", None, fetch_call=fetch)
        assert loaded is not None
        assert participant_phone_from_call_log(loaded) == "+919876543210"

    asyncio.run(_run())


def test_resolve_call_log_fetch_failure_returns_none() -> None:
    async def fetch(_call_id: str, _org_id: str) -> dict:
        raise RuntimeError("backend down")

    async def _run() -> None:
        assert await resolve_call_log("org", "c1", None, fetch_call=fetch) is None

    asyncio.run(_run())


def test_phones_from_call_log_normalizes_indian() -> None:
    phones = phones_from_call_log(
        {"from_number": "9876543210", "to_number": "9123456789", "call_type": "inbound"}
    )
    assert phones is not None
    assert phones.from_number == "+919876543210"


@dataclass
class _FakeLLMService:
    call_id: str | None = None
    participant_phone: str | None = None
    greeting: str | None = None
    _use_participant_phone: bool = True

    def set_call_id(self, call_id: str | None) -> None:
        self.call_id = call_id

    def set_participant_phone(self, phone: str | None) -> None:
        self.participant_phone = phone

    def set_spoken_greeting(self, text: str | None) -> None:
        self.greeting = text


class _FakeLLMSwitcher:
    def __init__(self, services: list[_FakeLLMService]) -> None:
        self.services = services


def test_wire_llm_call_session_skips_when_participant_phone_disabled() -> None:
    svc = _FakeLLMService()
    svc._use_participant_phone = False
    llm = _FakeLLMSwitcher([svc])
    wire_llm_call_session(llm, call_id="call-1", participant_phone="+919876543210")
    assert svc.participant_phone is None


def test_wire_llm_call_session_fan_out() -> None:
    svc = _FakeLLMService()
    llm = _FakeLLMSwitcher([svc])
    wire_llm_call_session(
        llm,
        call_id="call-1",
        participant_phone="+919876543210",
        spoken_greeting="Hello",
    )
    assert svc.call_id == "call-1"
    assert svc.participant_phone == "+919876543210"
    assert svc.greeting == "Hello"
