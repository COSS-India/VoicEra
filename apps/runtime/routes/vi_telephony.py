"""Thin Vodafone Idea (VI) WebSocket media routes.

Session logic lives in ``apps.telephony.providers.vi.stream_session``.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, WebSocket

from apps.runtime.services.agent_routing import agent_category, telephony_provider
from apps.runtime.services.backend import BackendError, backend_client
from apps.runtime.services.pipecat.runners import run_telephony_bot
from apps.telephony.providers.vi.stream_session import (
    ViStreamDeps,
    integration_info,
    run_vi_stream_session,
)

router = APIRouter(tags=["vi-telephony"])


def _deps() -> ViStreamDeps:
    return ViStreamDeps(
        get_agent=backend_client.get_agent,
        get_agent_by_phone=backend_client.get_agent_by_phone,
        create_inbound_call=backend_client.create_inbound_call,
        run_bot=run_telephony_bot,
        agent_category=agent_category,
        telephony_provider=telephony_provider,
        backend_error_type=BackendError,
    )


@router.websocket("/vi/stream")
async def vi_stream_websocket(websocket: WebSocket) -> None:
    """Static VI streaming endpoint; agent resolved from DNI / custom params."""
    await run_vi_stream_session(websocket, _deps())


@router.get("/vi/integration-info")
async def vi_integration_info() -> dict[str, Any]:
    """Return portal WSS URL hints for operators."""
    return integration_info(os.environ.get("VOICE_SERVER_BASE_URL") or "")
