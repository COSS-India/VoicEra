"""Audio tap: Nemotron ASR transcript of each utterance, emitted at end of speech."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    StartFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from apps.runtime.services.language_switch.frames import NemotronTranscriptFrame
from apps.runtime.services.language_switch.lid.buffer import SpeechBuffer
from apps.runtime.services.language_switch.lid.client import NemotronClient

_PRE_ROLL_SEC = 0.5
_MAX_BUFFER_SEC = 30.0
# Shorter bursts are noise; skip Nemotron for them.
_MIN_AUDIO_SEC = 0.5


class LidTapProcessor(FrameProcessor):
    """Pass-through audio tap that transcribes each utterance with Nemotron.

    The audio keeps flowing to the main ASR untouched. At end of speech the whole
    utterance goes to Nemotron ``/transcribe`` in the background, and the tap
    emits exactly one ``NemotronTranscriptFrame`` per utterance (empty text when
    Nemotron was skipped, failed, or superseded by new speech). ``LidTurnGate``
    does the judging.

    The Silero VAD lives in the user aggregator and broadcasts its VAD frames
    upstream, where this processor observes them.
    """

    def __init__(self, *, client: NemotronClient, sample_rate: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client = client
        self._buffer = SpeechBuffer(sample_rate)
        self._speaking = False
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            self._closed = False
        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self._shutdown()
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            await self._cancel_inflight()
            self._speaking = True
            self._buffer.keep_last(_PRE_ROLL_SEC)
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            await self._on_speech_stopped()
        elif direction == FrameDirection.DOWNSTREAM and isinstance(
            frame, InputAudioRawFrame
        ):
            self._buffer.append(bytes(frame.audio))
            self._buffer.trim_to_max_duration(
                _MAX_BUFFER_SEC if self._speaking else _PRE_ROLL_SEC
            )

        await self.push_frame(frame, direction)

    async def _on_speech_stopped(self) -> None:
        was_speaking, self._speaking = self._speaking, False
        if not was_speaking or self._closed:
            self._buffer.reset()
            return
        duration = self._buffer.duration_sec
        pcm = self._buffer.pcm_snapshot()
        wav = self._buffer.wav_16k_from_pcm(pcm) if pcm else b""
        self._buffer.reset()
        if not wav or duration < _MIN_AUDIO_SEC:
            await self.push_frame(NemotronTranscriptFrame(), FrameDirection.DOWNSTREAM)
            return
        self._task = asyncio.create_task(self._transcribe(wav, duration))

    async def _transcribe(self, wav: bytes, duration: float) -> None:
        text = ""
        try:
            text = await self._client.transcribe(wav)
        except asyncio.CancelledError:
            pass  # superseded by new speech or shutdown
        except Exception as exc:
            logger.warning("LidTapProcessor Nemotron task error: {}", exc)
        logger.info("LidTapProcessor nemotron audio_s={:.2f} text={!r}", duration, text)
        if not self._closed:
            await self.push_frame(NemotronTranscriptFrame(text=text), FrameDirection.DOWNSTREAM)

    async def _cancel_inflight(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _shutdown(self) -> None:
        self._closed = True
        self._speaking = False
        self._buffer.reset()
        await self._cancel_inflight()
        await self._client.aclose()
