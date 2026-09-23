"""Admission refusals from the API must close the socket, not run the call."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from apps.runtime.routes.agent import _close_if_denied
from apps.runtime.services.backend import BackendError


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 503])
async def test_admission_refusal_closes_socket(status_code):
    websocket = AsyncMock()
    assert await _close_if_denied(websocket, BackendError("denied", status_code))
    websocket.close.assert_awaited_once_with(code=1013, reason="Call limit reached")


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [None, 404, 500])
async def test_other_failures_keep_best_effort_fallback(status_code):
    websocket = AsyncMock()
    assert not await _close_if_denied(websocket, BackendError("oops", status_code))
    websocket.close.assert_not_awaited()
