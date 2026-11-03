"""Thin Plivo recording callback.

Parse and download logic lives in ``apps.telephony.providers.plivo.recording``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response
from loguru import logger

from apps.runtime.routes.provider_recording import ingest_provider_recording
from apps.runtime.services.backend import BackendError, backend_client
from apps.telephony.provider_recording import ProviderRecordingRef
from apps.telephony.providers.plivo.recording import (
    download_ready_recording,
    parse_recording_callback,
)
from apps.telephony.registry import build_config, create_client
from apps.telephony.webhooks import decode_webhook_body

router = APIRouter(tags=["plivo-telephony"])


async def _webhook_payload(request: Request) -> dict[str, Any]:
    raw = await request.body()
    parsed = decode_webhook_body(raw)
    try:
        form = dict(await request.form())
    except Exception:
        form = {}
    merged = dict(parsed)
    for key, value in form.items():
        merged.setdefault(key, value)
    for key, value in request.query_params.items():
        merged.setdefault(key, value)
    return merged


async def _load_plivo_client(provider_call_sid: str):
    try:
        call = await backend_client.get_call_by_provider_sid(provider_call_sid)
    except BackendError as exc:
        logger.warning("Plivo recording CallLog lookup failed: {}", exc)
        return None
    org_id = str(call.get("org_id") or "").strip()
    provider = str(call.get("telephony_provider") or "").strip()
    if not org_id or not provider:
        return None
    try:
        auth = await backend_client.get_provider_auth(provider, org_id)
        config = build_config(
            provider,
            **{k: v for k, v in auth.items() if v is not None and str(v).strip()},
        )
        return create_client(config)
    except Exception as exc:
        logger.warning("Plivo recording client load failed: {}", exc)
        return None


@router.post("/plivo/recording-webhook")
async def plivo_recording_webhook(request: Request) -> Response:
    """Plivo Record API callback. Download the file, polling until it is ready."""
    payload = await _webhook_payload(request)
    parsed = parse_recording_callback(payload)
    if parsed is None:
        logger.warning(
            "Plivo recording webhook missing call_uuid content_type={} keys={}",
            request.headers.get("content-type", ""),
            sorted(str(key) for key in payload),
        )
        return PlainTextResponse("call_uuid is required", status_code=400)

    client = await _load_plivo_client(parsed.call_uuid)
    if client is None:
        return PlainTextResponse("call log not found", status_code=404)

    audio, recording_url = await download_ready_recording(
        client,
        call_uuid=parsed.call_uuid,
        recording_id=parsed.recording_id,
        recording_url=parsed.recording_url,
    )
    if not audio:
        return PlainTextResponse("recording not ready", status_code=502)

    return await ingest_provider_recording(
        ProviderRecordingRef(
            provider_call_sid=parsed.call_uuid,
            recording_url=recording_url,
        ),
        audio=audio,
        provider_label="Plivo",
    )
