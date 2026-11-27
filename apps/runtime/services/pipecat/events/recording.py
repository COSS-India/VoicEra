"""Call recording handlers for the Pipecat pipeline."""

from __future__ import annotations

from typing import Any

from loguru import logger

from apps.runtime.services.pipecat.audio import wav_bytes
from apps.runtime.services.privacy.audio import recording_enabled
from apps.runtime.services.privacy.redaction import is_enabled as pii_redaction_enabled
from apps.runtime.services.storage.call_artifacts import save_and_link
from apps.runtime.services.storage.recording import (
    CallRecording,
    TimedAudioBufferProcessor,
)


def register_recording_handlers(
    audiobuffer: Any,
    *,
    org_id: str,
    call_id: str | None,
) -> CallRecording | None:
    """Store the call recording at call end.

    - ``CALL_RECORDING_ENABLED=false``: nothing is recorded or stored.
    - PII redaction off: the mixed recording is uploaded as soon as the call ends.
    - PII redaction on: the tracks are held in memory and uploaded by
      ``CallRecording.flush`` once the transcript is redacted, with PII muted.
    """
    if not call_id:
        return None
    if not recording_enabled():
        logger.info("Call recording disabled (CALL_RECORDING_ENABLED=false) call_id={}", call_id)
        return None

    if pii_redaction_enabled() and isinstance(audiobuffer, TimedAudioBufferProcessor):
        recording = CallRecording(org_id=org_id, call_id=call_id, recorder=audiobuffer)

        @audiobuffer.event_handler("on_track_audio_data")
        async def on_track_audio_data(
            buffer: Any, user_audio: bytes, bot_audio: bytes, audio_sample_rate: int, num_channels: int
        ) -> None:
            recording.hold(user_audio, bot_audio, audio_sample_rate)

        return recording

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

    return None
