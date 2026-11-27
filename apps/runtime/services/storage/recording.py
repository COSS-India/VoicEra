"""System call recording with PII muting, uploaded to MinIO at call end.

Objects are stored at ``voicera-calls/{org_id}/{call_id}/recording.wav``.

``TimedAudioBufferProcessor`` is Pipecat's stock recorder plus a note of when each
agent sentence was played. ``CallRecording`` holds the caller and agent tracks in
memory when the call ends, mutes what the transcript redaction found once the
transcript is ready, mixes them and uploads only the muted version. The
unmuted audio never leaves this process's memory.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from typing import Any

from loguru import logger
from pipecat.audio.utils import mix_audio
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.processors.frame_processor import FrameDirection

from apps.runtime.services.pipecat.audio import wav_bytes
from apps.runtime.services.privacy.audio import (
    AgentSegment,
    TurnTiming,
    mute,
    plan_mutes,
)
from apps.runtime.services.storage.call_artifacts import save_and_link

# How long call end waits for the recorder to hand over its tracks.
_TRACKS_TIMEOUT_SECS = 10.0


class TimedAudioBufferProcessor(AudioBufferProcessor):
    """Stock ``AudioBufferProcessor`` that also records agent sentence timings.

    It sits right after ``transport.output()``, where each sentence's text
    (``TTSTextFrame``) arrives just after that sentence's audio has been played.
    So a sentence runs from the previous sentence's text, or from the moment the
    agent started speaking, to its own text. Times are in seconds from the start
    of the recording, the same wall clock the recorder aligns its tracks to.

    The recorder's tracks begin with the first audio it receives, not when
    recording is switched on, so the clock starts at the first audio (or
    speaking) frame.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.recording_started_at: float | None = None
        self.agent_segments: list[AgentSegment] = []
        self._segment_start: float | None = None
        self._awaiting_first_audio = False

    async def start_recording(self) -> None:
        await super().start_recording()
        self.recording_started_at = None
        self.agent_segments = []
        self._segment_start = None
        self._awaiting_first_audio = True

    def _offset(self) -> float:
        return time.time() - (self.recording_started_at or time.time())

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if self._awaiting_first_audio and isinstance(
            frame,
            (InputAudioRawFrame, OutputAudioRawFrame, BotStartedSpeakingFrame, UserStartedSpeakingFrame),
        ):
            self.recording_started_at = time.time()
            self._awaiting_first_audio = False
        if self.recording_started_at is not None and direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, BotStartedSpeakingFrame):
                self._segment_start = self._offset()
            elif isinstance(frame, TTSTextFrame) and frame.text and frame.text.strip():
                now = self._offset()
                start = self._segment_start if self._segment_start is not None else now
                self.agent_segments.append(AgentSegment(start, now, frame.text))
                self._segment_start = now
            elif isinstance(frame, BotStoppedSpeakingFrame) and self._segment_start is not None:
                now = self._offset()
                # Audio after the last sentence's text: cut off by an interruption.
                if now - self._segment_start > 0.25:
                    self.agent_segments.append(AgentSegment(self._segment_start, now, None))
                self._segment_start = None
        await super().process_frame(frame, direction)


class CallRecording:
    """Holds one call's tracks until the transcript is redacted, then uploads."""

    def __init__(self, *, org_id: str, call_id: str, recorder: TimedAudioBufferProcessor) -> None:
        self._org_id = org_id
        self._call_id = call_id
        self._recorder = recorder
        self._tracks: tuple[bytes, bytes, int] | None = None
        self._ready = asyncio.Event()
        self._flushed = False

    def hold(self, user: bytes, bot: bytes, sample_rate: int) -> None:
        self._tracks = (user, bot, sample_rate)
        self._ready.set()

    def render(self, turns: Sequence[TurnTiming]) -> bytes | None:
        """The recording as it is stored: PII muted, caller and agent mixed to mono."""
        if self._tracks is None:
            return None
        user, bot, sample_rate = self._tracks
        started_at = self._recorder.recording_started_at or 0.0
        user_windows, agent_windows = plan_mutes(turns, self._recorder.agent_segments, started_at)
        if user_windows or agent_windows:
            logger.info(
                "Muting PII in recording call_id={} caller_parts={} agent_parts={}",
                self._call_id,
                len(user_windows),
                len(agent_windows),
            )
        user = mute(user, sample_rate, user_windows)
        bot = mute(bot, sample_rate, agent_windows)
        return wav_bytes(mix_audio(user, bot), sample_rate, 1)

    async def flush(self, turns: Sequence[TurnTiming]) -> None:
        """Mute, mix and upload the recording (once per call)."""
        if self._flushed:
            return
        self._flushed = True
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=_TRACKS_TIMEOUT_SECS)
        except TimeoutError:
            logger.warning("No recording audio arrived call_id={}", self._call_id)
            return
        try:
            data = self.render(turns)
        except Exception:  # noqa: BLE001
            # Never store the recording unmuted because muting failed.
            logger.exception("Recording PII muting failed; not storing call_id={}", self._call_id)
            return
        finally:
            self._tracks = None
        if data is None:
            return
        await save_and_link(
            org_id=self._org_id,
            call_id=self._call_id,
            filename="recording.wav",
            data=data,
            content_type="audio/wav",
            url_field="recording_url",
        )
