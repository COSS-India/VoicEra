"""Plivo native call recording via Record API."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Optional

from apps.telephony.base import (
    DEFAULT_POLL_ATTEMPTS,
    DEFAULT_POLL_INTERVAL_SECS,
    extract_recording_id,
    extract_recording_url,
    request_bytes,
    request_json,
)
from apps.telephony.provider_recording import ProviderRecordingRef

if TYPE_CHECKING:
    from apps.telephony.providers.plivo.client import PlivoClient

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_POLL_ATTEMPTS",
    "DEFAULT_POLL_INTERVAL_SECS",
    "DEFAULT_RECORDING_TIME_LIMIT_SECS",
    "start_call_recording",
    "start_provider_recording",
    "parse_recording_callback",
    "download_ready_recording",
    "recording_callback_url",
    "fetch_recording_metadata",
    "list_recordings_for_call",
    "download_recording",
    "wait_and_download_recording",
]

DEFAULT_RECORDING_TIME_LIMIT_SECS = 3600
_CALL_UUID_KEYS = ("call_uuid", "calluuid", "aleguuid", "bleguuid")
_RECORD_URL_KEYS = ("record_url", "recording_url", "recordurl", "recordingurl")
_RECORDING_ID_KEYS = ("recording_id", "recordingid", "recording_uuid", "recordinguuid")


@dataclass(frozen=True)
class PlivoRecordingCallback:
    """Record API callback. ``record_url`` may be empty until the file is ready."""

    call_uuid: str
    recording_url: str | None = None
    recording_id: str | None = None


def recording_callback_url() -> str | None:
    """Public URL Plivo POSTs when a Record API recording is ready."""
    base = (os.environ.get("VOICE_SERVER_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/plivo/recording-webhook"


def _flatten(payload: Mapping[str, Any]) -> dict[str, str]:
    flat: dict[str, str] = {}

    def add(key: Any, value: Any) -> None:
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if isinstance(value, Mapping):
            for nested_key, nested_value in value.items():
                add(nested_key, nested_value)
            return
        if value is None:
            return
        text = str(value).strip()
        if not text:
            return
        flat.setdefault(str(key).strip().lower(), text)

    for key, value in payload.items():
        add(key, value)
    return flat


def _first_text(payload: Mapping[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value:
            return value
    return None


def _http_url(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return None


def parse_recording_callback(
    payload: Mapping[str, Any] | None,
) -> PlivoRecordingCallback | None:
    """Map a Plivo Record API callback.

    Documented fields are ``call_uuid``, ``record_url``, and ``recording_id``.
    ``record_url`` can be absent while Plivo is still publishing the file.
    """
    if not payload:
        return None
    flat = _flatten(payload)
    call_uuid = _first_text(flat, _CALL_UUID_KEYS)
    if not call_uuid:
        return None
    record_url = _http_url(_first_text(flat, _RECORD_URL_KEYS))
    if record_url is None:
        for key, value in flat.items():
            if "url" in key and (candidate := _http_url(value)):
                record_url = candidate
                break
    return PlivoRecordingCallback(
        call_uuid=call_uuid,
        recording_url=record_url,
        recording_id=_first_text(flat, _RECORDING_ID_KEYS),
    )


def recording_media_url(client: "PlivoClient", recording_id: str) -> str:
    """Direct recording file URL documented by Plivo."""
    auth_id = client.credentials.auth_id
    return (
        f"https://media.plivo.com/v1/Account/{auth_id}/Recording/{recording_id}.mp3"
    )


async def _download_url(client: "PlivoClient", url: str) -> Optional[bytes]:
    """GET a recording file. Public by default; retry with Basic auth if that fails."""
    audio = await request_bytes(url, provider_label=client.PROVIDER_LABEL)
    if audio:
        return audio
    return await download_recording(client, url)


async def start_call_recording(
    client: "PlivoClient",
    call_uuid: str,
    time_limit_secs: int,
) -> Optional[str]:
    """Start Plivo call recording. Returns recording_id or None on failure."""
    url = client.account_url(f"Call/{call_uuid}/Record/")
    payload: dict[str, Any] = {
        "time_limit": time_limit_secs,
        "file_format": "mp3",
        "callback_method": "POST",
    }
    callback = recording_callback_url()
    if callback:
        payload["callback_url"] = callback
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


async def download_ready_recording(
    client: "PlivoClient",
    *,
    call_uuid: str,
    recording_id: str | None = None,
    recording_url: str | None = None,
    max_attempts: int = DEFAULT_POLL_ATTEMPTS,
    interval_secs: float = DEFAULT_POLL_INTERVAL_SECS,
) -> tuple[Optional[bytes], Optional[str]]:
    """Download the recording, polling Plivo's Recording API until the file exists.

    Tries the callback ``record_url`` and the direct media URL first, then
    ``GET Recording/{recording_id}/`` and ``GET Recording/?call_uuid=``.
    """
    url = _http_url(recording_url)
    rid = str(recording_id or "").strip() or None
    for attempt in range(1, max_attempts + 1):
        candidates: list[str] = []
        if url:
            candidates.append(url)
        if rid:
            candidates.append(recording_media_url(client, rid))
        for candidate in candidates:
            audio = await _download_url(client, candidate)
            if audio:
                return audio, candidate

        metadata = None
        if rid:
            metadata = await fetch_recording_metadata(client, rid)
        if metadata is None and call_uuid:
            metadata = await list_recordings_for_call(client, call_uuid)
        if metadata:
            found_id = extract_recording_id(metadata)
            if found_id:
                rid = found_id
            found_url = _http_url(extract_recording_url(metadata))
            if found_url:
                url = found_url
                audio = await _download_url(client, found_url)
                if audio:
                    return audio, found_url

        if attempt < max_attempts:
            logger.info(
                "Plivo recording not ready (attempt %s/%s) call_uuid=%s recording_id=%s",
                attempt,
                max_attempts,
                call_uuid,
                rid,
            )
            await asyncio.sleep(interval_secs)

    logger.warning(
        "Plivo recording unavailable after %s attempts call_uuid=%s recording_id=%s",
        max_attempts,
        call_uuid,
        rid,
    )
    return None, url


async def start_provider_recording(
    client: "PlivoClient",
    call_uuid: str,
) -> Optional[str]:
    """Start a provider recording for one live Plivo call."""
    sid = str(call_uuid or "").strip()
    if not sid:
        return None
    return await start_call_recording(
        client, sid, DEFAULT_RECORDING_TIME_LIMIT_SECS
    )


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
