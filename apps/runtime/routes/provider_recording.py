"""Shared provider-recording ingest — resolve CallLog, download, MinIO link.

Provider routes parse their own webhook shape into ``ProviderRecordingRef``,
then call ``ingest_provider_recording``.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse, PlainTextResponse, Response
from loguru import logger

from apps.runtime.services.backend import BackendError, backend_client
from apps.runtime.services.storage.call_artifacts import save_and_link
from apps.telephony.provider_recording import (
    ProviderRecordingRef,
    download_recording_url,
    recording_filename_for_url,
)


async def ingest_provider_recording(
    ref: ProviderRecordingRef,
    *,
    audio: bytes | None = None,
    provider_label: str = "Telephony",
) -> Response:
    """Store provider recording bytes (or download ``ref.recording_url``) on CallLog."""
    provider_call_sid = str(ref.provider_call_sid or "").strip()
    if not provider_call_sid:
        return PlainTextResponse("provider_call_sid is required", status_code=400)

    try:
        call = await backend_client.get_call_by_provider_sid(provider_call_sid)
    except BackendError as exc:
        logger.warning(
            "Provider recording CallLog lookup failed sid={}: {}",
            provider_call_sid,
            exc,
        )
        return PlainTextResponse(str(exc), status_code=404)

    call_id = str(call.get("call_id") or "").strip()
    org_id = str(call.get("org_id") or "").strip()
    if not call_id or not org_id:
        return PlainTextResponse("call log missing call_id or org_id", status_code=404)

    recording_url = str(ref.recording_url or "").strip() or None
    data = audio
    if data is None:
        if not recording_url:
            return PlainTextResponse(
                "recording_url or audio bytes required",
                status_code=400,
            )
        data = await download_recording_url(
            recording_url,
            provider_label=provider_label,
        )
    if not data:
        logger.error(
            "Provider recording download failed call_id={} url={}",
            call_id,
            (recording_url or "")[:200],
        )
        return PlainTextResponse("failed to download recording", status_code=502)

    filename = (
        recording_filename_for_url(recording_url)
        if recording_url
        else "provider_recording.wav"
    )
    content_type = "audio/mpeg" if filename.endswith(".mp3") else "audio/wav"
    linked = await save_and_link(
        org_id=org_id,
        call_id=call_id,
        filename=filename,
        data=data,
        content_type=content_type,
        url_field="provider_recording_url",
    )
    if not linked:
        return PlainTextResponse("failed to store provider recording", status_code=502)

    return JSONResponse(
        {
            "status": "ok",
            "call_id": call_id,
            "provider_call_sid": provider_call_sid,
        }
    )
