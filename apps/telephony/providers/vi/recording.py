"""VI carrier recording APIs are unused (Pipecat AudioBuffer only)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from apps.telephony.base import DEFAULT_POLL_ATTEMPTS, DEFAULT_POLL_INTERVAL_SECS

if TYPE_CHECKING:
    from apps.telephony.providers.vi.client import ViClient

__all__ = [
    "DEFAULT_POLL_ATTEMPTS",
    "DEFAULT_POLL_INTERVAL_SECS",
    "start_call_recording",
    "fetch_recording_metadata",
    "download_recording",
    "wait_and_download_recording",
]


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
    del client, recording_url
    return None


async def wait_and_download_recording(
    client: "ViClient",
    recording_id: str,
    max_attempts: int = DEFAULT_POLL_ATTEMPTS,
    interval_secs: float = DEFAULT_POLL_INTERVAL_SECS,
) -> Optional[bytes]:
    del client, recording_id, max_attempts, interval_secs
    return None
