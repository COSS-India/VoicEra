"""VI stream session call-log routing tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from apps.telephony.providers.vi.stream_session import (
    ViStreamDeps,
    _is_outbound_stream,
    _phones_equal,
    ensure_call_log,
)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("+919876543210", "9876543210", True),
        ("919876543210", "9876543210", True),
        ("+919876543210", "919876543210", True),
        ("9876543210", "9876543210", True),
        ("+919876543210", "+919876543211", False),
        ("unknown", "unknown", False),
        ("", "9876543210", False),
        ("9876543210", "unknown", False),
    ],
)
def test_phones_equal(a: str, b: str, expected: bool) -> None:
    assert _phones_equal(a, b) is expected


def test_is_outbound_stream_when_cli_equals_dni() -> None:
    assert _is_outbound_stream("+919876543210", "9876543210") is True
    assert _is_outbound_stream("9876543210", "+919999999999") is False


def _deps(
    *,
    inbound: AsyncMock | None = None,
    outbound: AsyncMock | None = None,
) -> ViStreamDeps:
    return ViStreamDeps(
        get_agent=AsyncMock(),
        get_agent_by_phone=AsyncMock(),
        create_inbound_call=inbound or AsyncMock(),
        create_outbound_call=outbound or AsyncMock(),
        run_bot=AsyncMock(),
        agent_category=lambda _a: "telephony",
        telephony_provider=lambda _a: "vi",
        backend_error_type=RuntimeError,
    )


@pytest.mark.asyncio
async def test_ensure_call_log_outbound_when_cli_equals_dni() -> None:
    outbound = AsyncMock(return_value={"call_id": "out-1"})
    inbound = AsyncMock()
    deps = _deps(inbound=inbound, outbound=outbound)
    agent: dict[str, Any] = {"org_id": "org-1", "agent_id": "agent-1"}

    call_id = await ensure_call_log(
        deps,
        agent,
        call_sid="sid-1",
        cli="+919876543210",
        dni="9876543210",
    )

    assert call_id == "out-1"
    outbound.assert_awaited_once_with(
        "org-1",
        "agent-1",
        provider_call_sid="sid-1",
        from_number="+919876543210",
        to_number="unknown",
    )
    inbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_call_log_inbound_when_cli_differs_from_dni() -> None:
    outbound = AsyncMock()
    inbound = AsyncMock(return_value={"call_id": "in-1"})
    deps = _deps(inbound=inbound, outbound=outbound)
    agent: dict[str, Any] = {"org_id": "org-1", "agent_id": "agent-1"}

    call_id = await ensure_call_log(
        deps,
        agent,
        call_sid="sid-2",
        cli="912345678901",
        dni="9876543210",
    )

    assert call_id == "in-1"
    inbound.assert_awaited_once_with(
        "org-1",
        "agent-1",
        provider_call_sid="sid-2",
        from_number="912345678901",
        to_number="9876543210",
    )
    outbound.assert_not_awaited()
