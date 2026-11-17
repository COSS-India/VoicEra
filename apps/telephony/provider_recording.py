"""Shared provider-recording ingest (download URL → MinIO → CallLog).

Provider-specific webhook parsing and call-id extraction live under
``apps.telephony.providers.<id>``. This module only handles the common
store path once a provider has resolved ``provider_call_sid`` + a
downloadable ``recording_url``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import unquote, urlparse

from apps.telephony.base import request_bytes


@dataclass(frozen=True)
class ProviderRecordingRef:
    """Resolved carrier recording ready for ingest.

    Providers that expose a direct file URL set ``recording_url``.
    Providers that fetch via their Record API can omit the URL and pass
    bytes into ``ingest_provider_recording_bytes`` instead.
    """

    provider_call_sid: str
    recording_url: str | None = None


def recording_filename_for_url(url: str, *, default_ext: str = "wav") -> str:
    """Choose a MinIO object basename for a provider recording."""
    path = unquote(urlparse(str(url or "")).path)
    suffix = PurePosixPath(path).suffix.lstrip(".").lower()
    if suffix in {"wav", "mp3", "ogg", "amr", "mpeg"}:
        return f"provider_recording.{suffix}"
    return f"provider_recording.{default_ext}"


async def download_recording_url(
    url: str,
    *,
    timeout: float = 60.0,
    provider_label: str = "Telephony",
) -> Optional[bytes]:
    """HTTP GET the recording; return bytes or ``None`` on failure/empty body."""
    data = await request_bytes(
        url,
        timeout=timeout,
        provider_label=provider_label,
    )
    if not data:
        return None
    return data
