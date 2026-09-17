"""VI carrier recording APIs — intentionally unused.

VoicERA records VI calls via the Pipecat AudioBuffer pipeline, not VI CPaaS.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from apps.telephony.providers.vi.client import ViClient

DEFAULT_POLL_ATTEMPTS = 1
DEFAULT_POLL_INTERVAL_SECS = 1.0


async def start_call_recording(
    client: "ViClient", call_sid: str, time_limit_secs: int
) -> Optional[str]:
    del client, call_sid, time_limit_secs
    return None


async def fetch_recording_metadata(
    client: "ViClient", recording_id: str
) -> Optional[dict]:
    del client, recording_id
    return None


async def download_recording(client: "ViClient", recording_url: str) -> Optional[bytes]:
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
