"""Vobiz native call recording via Record API."""

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
    from apps.telephony.providers.vobiz.client import VobizClient

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_POLL_ATTEMPTS",
    "DEFAULT_POLL_INTERVAL_SECS",
    "start_call_recording",
    "fetch_recording_metadata",
    "download_recording",
    "wait_and_download_recording",
]


async def start_call_recording(
    client: "VobizClient",
    call_sid: str,
    time_limit_secs: int,
) -> Optional[str]:
    """Start Vobiz call recording. Returns recording_id or None on failure."""
    url = client.account_url(f"Call/{call_sid}/Record/")
    payload = {
        "time_limit": time_limit_secs,
        "file_format": "mp3",
        "record_channel_type": "mono",
    }
    data, err = await request_json(
        "POST",
        url,
        headers=client.auth_headers(),
        json=payload,
        provider_label=client.PROVIDER_LABEL,
    )
    if err or data is None:
        logger.error("Failed to start Vobiz recording for %s: %s", call_sid, err)
        return None
    recording_id = extract_recording_id(data)
    logger.info(
        "Started Vobiz recording: call_sid=%s recording_id=%s", call_sid, recording_id
    )
    return recording_id


async def fetch_recording_metadata(
    client: "VobizClient",
    recording_id: str,
) -> Optional[dict]:
    """Fetch recording metadata from Vobiz API."""
    url = client.account_url(f"Recording/{recording_id}/")
    data, err = await request_json(
        "GET",
        url,
        headers=client.auth_headers(include_content_type=False),
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        logger.debug(
            "Vobiz recording metadata fetch failed for %s: %s", recording_id, err
        )
        return None
    return data


async def download_recording(
    client: "VobizClient",
    recording_url: str,
) -> Optional[bytes]:
    """Download recording file bytes from Vobiz URL."""
    headers = {
        "X-Auth-ID": client.credentials.auth_id,
        "X-Auth-Token": client.credentials.auth_token,
    }
    return await request_bytes(
        recording_url,
        headers=headers,
        provider_label=client.PROVIDER_LABEL,
    )


async def wait_and_download_recording(
    client: "VobizClient",
    recording_id: str,
    max_attempts: int = DEFAULT_POLL_ATTEMPTS,
    interval_secs: float = DEFAULT_POLL_INTERVAL_SECS,
) -> Optional[bytes]:
    """Poll until recording_url is ready, then download once."""
    for attempt in range(1, max_attempts + 1):
        metadata = await fetch_recording_metadata(client, recording_id)
        if metadata:
            recording_url = extract_recording_url(metadata)
            if recording_url:
                audio_bytes = await download_recording(client, recording_url)
                if audio_bytes:
                    logger.info(
                        "Downloaded Vobiz recording %s (%s bytes)",
                        recording_id,
                        len(audio_bytes),
                    )
                    return audio_bytes

        if attempt < max_attempts:
            logger.debug(
                "Vobiz recording not ready (attempt %s/%s), retrying...",
                attempt,
                max_attempts,
            )
            await asyncio.sleep(interval_secs)

    logger.warning(
        "Vobiz recording not ready after %s attempts: %s",
        max_attempts,
        recording_id,
    )
    return None
