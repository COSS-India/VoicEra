"""VI carrier recording — portal hangup webhook parse + HTTP download."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Mapping, Optional
from urllib.parse import parse_qs, unquote, urlparse

from apps.telephony.base import DEFAULT_POLL_ATTEMPTS, DEFAULT_POLL_INTERVAL_SECS
from apps.telephony.provider_recording import (
    ProviderRecordingRef,
    download_recording_url,
)

if TYPE_CHECKING:
    from apps.telephony.providers.vi.client import ViClient

__all__ = [
    "DEFAULT_POLL_ATTEMPTS",
    "DEFAULT_POLL_INTERVAL_SECS",
    "start_call_recording",
    "fetch_recording_metadata",
    "download_recording",
    "wait_and_download_recording",
    "parse_hangup_recording_webhook",
]

# VI portal "ApiCall after HangUp" maps $RecordVoice → recording_url / RecordVoice.
_RECORDING_URL_KEYS = ("recording_url", "recordingUrl", "RecordVoice", "record_voice")
_CALL_ID_QUERY_KEYS = ("callid", "call_id", "callId", "CallId")


def _recording_url_from_payload(payload: Mapping[str, Any] | None) -> Optional[str]:
    if not payload:
        return None
    for key in _RECORDING_URL_KEYS:
        raw = payload.get(key)
        if raw is None:
            continue
        url = str(raw).strip()
        if url:
            return url
    return None


def _call_id_from_recording_url(url: str) -> Optional[str]:
    """VI recording URLs embed the stream ``call_id`` (CallLog.provider_call_sid)."""
    raw = str(url or "").strip()
    if not raw:
        return None

    parsed = urlparse(raw)
    query = parse_qs(parsed.query, keep_blank_values=False)
    for key in _CALL_ID_QUERY_KEYS:
        values = query.get(key) or []
        if values:
            sid = unquote(str(values[0])).strip()
            if sid:
                return sid

    parts = [p for p in PurePosixPath(unquote(parsed.path)).parts if p and p != "/"]
    for part in reversed(parts):
        lower = part.lower()
        if "." in part and lower.rsplit(".", 1)[-1] in {
            "wav",
            "mp3",
            "ogg",
            "amr",
            "mpeg",
            "bin",
        }:
            stem = part.rsplit(".", 1)[0]
            if stem:
                return stem
        if part not in {".", ".."} and len(part) >= 4:
            return part
    return None


def parse_hangup_recording_webhook(
    payload: Mapping[str, Any] | None,
) -> ProviderRecordingRef | None:
    """Parse VI hangup recording webhook into a shared ingest ref."""
    recording_url = _recording_url_from_payload(payload)
    if not recording_url:
        return None
    provider_call_sid = _call_id_from_recording_url(recording_url)
    if not provider_call_sid:
        return None
    return ProviderRecordingRef(
        provider_call_sid=provider_call_sid,
        recording_url=recording_url,
    )


async def start_call_recording(
    client: "ViClient",
    call_sid: str,
    time_limit_secs: int,
) -> Optional[str]:
    del client, call_sid, time_limit_secs
    return None


async def fetch_recording_metadata(
    client: "ViClient",
    recording_id: str,
) -> Optional[dict]:
    del client, recording_id
    return None


async def download_recording(
    client: "ViClient",
    recording_url: str,
) -> Optional[bytes]:
    """Download a VI portal recording URL via HTTP GET."""
    del client
    return await download_recording_url(
        recording_url,
        provider_label="Vodafone Idea",
    )


async def wait_and_download_recording(
    client: "ViClient",
    recording_id: str,
    max_attempts: int = DEFAULT_POLL_ATTEMPTS,
    interval_secs: float = DEFAULT_POLL_INTERVAL_SECS,
) -> Optional[bytes]:
    del client, recording_id, max_attempts, interval_secs
    return None
