"""Thin Vodafone Idea (VI) WebSocket media routes.

Session logic lives in ``apps.telephony.providers.vi.stream_session``.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import PlainTextResponse, Response
from loguru import logger

from apps.runtime.routes.provider_recording import ingest_provider_recording
from apps.runtime.services.agent_routing import agent_category, telephony_provider
from apps.runtime.services.backend import BackendError, backend_client
from apps.runtime.services.pipecat.runners import run_telephony_bot
from apps.telephony.providers.vi.recording import parse_hangup_recording_webhook
from apps.telephony.providers.vi.stream_session import (
    ViStreamDeps,
    integration_info,
    run_vi_stream_session,
)
from apps.telephony.webhooks import decode_webhook_body

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


async def _webhook_payload(request: Request) -> dict[str, Any]:
    form_dict = decode_webhook_body(await request.body())
    if form_dict:
        return form_dict
    try:
        return dict(await request.form())
    except Exception:
        return {}


@router.post("/vi/recording-webhook")
async def vi_recording_webhook(request: Request) -> Response:
    """VI portal hangup callback — parse VI payload, then shared ingest."""
    payload = await _webhook_payload(request)
    ref = parse_hangup_recording_webhook(payload)
    if ref is None:
        if not any(
            str(payload.get(k) or "").strip()
            for k in ("recording_url", "recordingUrl", "RecordVoice", "record_voice")
        ):
            return PlainTextResponse("recording_url is required", status_code=400)
        logger.warning("VI recording webhook could not extract call id from payload")
        return PlainTextResponse(
            "could not extract call id from recording_url",
            status_code=400,
        )
    return await ingest_provider_recording(ref, provider_label="Vodafone Idea")
