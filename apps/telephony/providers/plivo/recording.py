"""Plivo native call recording via Record API."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from apps.telephony.base import (
    DEFAULT_POLL_ATTEMPTS,
    DEFAULT_POLL_INTERVAL_SECS,
    extract_recording_id,
    extract_recording_url,
    request_bytes,
    request_json,
)

if TYPE_CHECKING:
    from apps.telephony.providers.plivo.client import PlivoClient

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_POLL_ATTEMPTS",
    "DEFAULT_POLL_INTERVAL_SECS",
    "start_call_recording",
    "fetch_recording_metadata",
    "list_recordings_for_call",
    "download_recording",
    "wait_and_download_recording",
]


async def start_call_recording(
    client: "PlivoClient",
    call_uuid: str,
    time_limit_secs: int,
) -> Optional[str]:
    """Start Plivo call recording. Returns recording_id or None on failure."""
    url = client.account_url(f"Call/{call_uuid}/Record/")
    payload = {
        "time_limit": time_limit_secs,
        "file_format": "mp3",
    }
    data, err = await request_json(
        "POST",
        url,
        headers=client.auth_headers(include_content_type=True),
        auth=client.auth_tuple(),
        json=payload,
        provider_label=client.PROVIDER_LABEL,
    )
    if err or data is None:
        logger.error("Failed to start Plivo recording for %s: %s", call_uuid, err)
        return None
    recording_id = extract_recording_id(data)
    logger.info(
        "Started Plivo recording: call_uuid=%s recording_id=%s",
        call_uuid,
        recording_id,
    )
    return recording_id


async def fetch_recording_metadata(
    client: "PlivoClient",
    recording_id: str,
) -> Optional[dict]:
    """Fetch recording metadata from Plivo API."""
    url = client.account_url(f"Recording/{recording_id}/")
    data, err = await request_json(
        "GET",
        url,
        headers=client.auth_headers(),
        auth=client.auth_tuple(),
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        logger.debug(
            "Plivo recording metadata fetch failed for %s: %s", recording_id, err
        )
        return None
    return data


async def list_recordings_for_call(
    client: "PlivoClient",
    call_uuid: str,
) -> Optional[dict]:
    """List recordings for a call UUID (fallback when recording_id is unknown)."""
    url = client.account_url("Recording/")
    data, err = await request_json(
        "GET",
        url,
        headers=client.auth_headers(),
        auth=client.auth_tuple(),
        params={"call_uuid": call_uuid, "limit": 1},
        provider_label=client.PROVIDER_LABEL,
    )
    if err or data is None:
        logger.debug("Plivo recording list failed for call %s: %s", call_uuid, err)
        return None
    objects = data.get("objects") if isinstance(data, dict) else None
    if objects:
        return objects[0]
    return None


async def download_recording(
    client: "PlivoClient",
    recording_url: str,
) -> Optional[bytes]:
    """Download recording file bytes from Plivo URL (Basic auth)."""
    return await request_bytes(
        recording_url,
        auth=client.auth_tuple(),
        provider_label=client.PROVIDER_LABEL,
    )


async def wait_and_download_recording(
    client: "PlivoClient",
    recording_id: Optional[str] = None,
    call_uuid: Optional[str] = None,
    max_attempts: int = DEFAULT_POLL_ATTEMPTS,
    interval_secs: float = DEFAULT_POLL_INTERVAL_SECS,
) -> Optional[bytes]:
    """Poll until recording_url is ready, then download once."""
    resolved_id = recording_id

    for attempt in range(1, max_attempts + 1):
        metadata = None
        if resolved_id:
            metadata = await fetch_recording_metadata(client, resolved_id)
        elif call_uuid and attempt == 1:
            metadata = await list_recordings_for_call(client, call_uuid)
            if metadata:
                resolved_id = extract_recording_id(metadata)

        if metadata:
            recording_url = extract_recording_url(metadata)
            if recording_url:
                audio_bytes = await download_recording(client, recording_url)
                if audio_bytes:
                    logger.info(
                        "Downloaded Plivo recording %s (%s bytes)",
                        resolved_id or call_uuid,
                        len(audio_bytes),
                    )
                    return audio_bytes

        if attempt < max_attempts:
            logger.debug(
                "Plivo recording not ready (attempt %s/%s), retrying...",
                attempt,
                max_attempts,
            )
            await asyncio.sleep(interval_secs)

    logger.warning(
        "Plivo recording not ready after %s attempts: recording_id=%s call_uuid=%s",
        max_attempts,
        recording_id,
        call_uuid,
    )
    return None
