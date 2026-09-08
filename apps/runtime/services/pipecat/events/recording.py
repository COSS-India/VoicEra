"""Call recording handlers for the Pipecat pipeline."""

from __future__ import annotations

from typing import Any

from apps.runtime.services.pipecat.audio import wav_bytes
from apps.runtime.services.storage.call_artifacts import save_and_link


def register_recording_handlers(
    audiobuffer: Any,
    *,
    org_id: str,
    call_id: str | None,
) -> None:
    if not call_id:
        return

    @audiobuffer.event_handler("on_audio_data")
    async def on_audio_data(
        buffer: Any, audio: bytes, audio_sample_rate: int, num_channels: int
    ) -> None:
        await save_and_link(
            org_id=org_id,
            call_id=call_id,
            filename="recording.wav",
            data=wav_bytes(audio, audio_sample_rate, num_channels),
            content_type="audio/wav",
            url_field="recording_url",
        )
