"""Non-blocking Pipecat processor: tap user audio → LID → LanguageSwitchFrame."""

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

from apps.runtime.services.language_switch.frames import LanguageSwitchFrame
from apps.runtime.services.language_switch.lid.buffer import SpeechBuffer
from apps.runtime.services.language_switch.lid.client import LidClient, NemotronLidClient
from apps.runtime.services.language_switch.lid.config import LidConfig
from apps.runtime.services.language_switch.lid.policy import LidPolicy

# Trailing audio kept when VAD start arrives late (aggregator is after STT).
_PRE_ROLL_SEC = 0.5
# Cap idle/always-on capture so the buffer cannot grow without bound.
_MAX_BUFFER_SEC = 12.0


class LidTapProcessor(FrameProcessor):
    """Pass-through audio tap that identifies language after each user utterance.

    Never awaits LID on the audio critical path. First utterance STT stays on
    the primary language; a confident decision emits ``LanguageSwitchFrame`` so
    the agent reply and later turns use the detected language.

    VAD start/stop must be handled in **both** directions: with Silero attached
    to ``LLMUserAggregator``, Pipecat broadcasts ``VADUser*`` frames upstream
    from the aggregator (after STT). Audio still flows downstream. Ignoring
    upstream VAD left the tap enabled but never identifying.
    """

    def __init__(
        self,
        *,
        config: LidConfig,
        allowed_languages: list[str],
        primary_language: str,
        sample_rate: int,
        client: LidClient | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._config = config
        self._client: LidClient = client or NemotronLidClient(
            config.url,
            timeout_s=config.timeout_s,
        )
        self._owns_client = client is None
        self._buffer = SpeechBuffer(sample_rate)
        self._policy = LidPolicy(
            allowed_languages=frozenset(
                lang.strip().lower().split("-")[0]
                for lang in allowed_languages
                if lang and str(lang).strip()
            ),
            min_confidence=config.min_confidence,
            min_audio_sec=config.min_audio_sec,
            cooldown_sec=config.cooldown_sec,
            active_language=primary_language,
        )
        self._user_speaking = False
        self._identify_tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    @property
    def active_language(self) -> str:
        return self._policy.active_language

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            self._closed = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, (EndFrame, CancelFrame)):
            await self._shutdown()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LanguageSwitchFrame):
            lang = (frame.language or "").strip()
            if lang:
                self._policy.note_switch(lang)
                logger.info("LidTapProcessor active language -> {} (observed frame)", lang)
            await self.push_frame(frame, direction)
            return

        # VAD may arrive downstream (transport-owned analyzer) or upstream
        # (aggregator-owned analyzer — VoicEra's current wiring).
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._user_speaking = True
            # Keep a short pre-roll: VAD start is often late relative to audio
            # that already passed this tap on the downstream path.
            self._buffer.keep_last(_PRE_ROLL_SEC)
            logger.debug("LidTapProcessor speech start direction={}", direction)
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            was_speaking = self._user_speaking
            self._user_speaking = False
            if was_speaking:
                self._schedule_identify()
            else:
                # Stop without a matching start — still try if we have enough
                # continuously buffered audio (pre-roll path).
                if self._buffer.duration_sec >= self._config.min_audio_sec:
                    self._schedule_identify()
                else:
                    logger.debug(
                        "LidTapProcessor speech stop ignored (not speaking) direction={}",
                        direction,
                    )
        elif direction == FrameDirection.DOWNSTREAM and isinstance(
            frame, InputAudioRawFrame
        ):
            # Always capture a capped window so late upstream VAD start still
            # has recent PCM. While speaking the window grows with the utterance.
            self._buffer.append(bytes(frame.audio))
            if not self._user_speaking:
                self._buffer.trim_to_max_duration(_PRE_ROLL_SEC)
            else:
                self._buffer.trim_to_max_duration(_MAX_BUFFER_SEC)

        await self.push_frame(frame, direction)

    def _schedule_identify(self) -> None:
        if self._closed:
            return
        duration = self._buffer.duration_sec
        if duration < self._config.min_audio_sec:
            logger.info(
                "LidTapProcessor skip identify — short audio {:.2f}s < {:.2f}s",
                duration,
                self._config.min_audio_sec,
            )
            self._buffer.reset()
            return
        wav = self._buffer.take_wav_16k()
        if not wav:
            return
        task = asyncio.create_task(self._identify_and_maybe_switch(wav, duration))
        self._identify_tasks.add(task)
        task.add_done_callback(self._identify_tasks.discard)

    async def _identify_and_maybe_switch(self, wav: bytes, buffered_audio_sec: float) -> None:
        try:
            result = await self._client.identify(wav)
            if result is None:
                logger.info("LidTapProcessor identify returned no result — stay")
                return
            decision = self._policy.decide(result, buffered_audio_sec=buffered_audio_sec)
            logger.info(
                "LidTapProcessor decision={} lang={} conf={} reason={} audio_s={:.2f}",
                decision.outcome,
                decision.language,
                decision.confidence,
                decision.reason,
                buffered_audio_sec,
            )
            if decision.outcome != "switch" or not decision.language:
                return
            if self._closed:
                return
            self._policy.note_switch(decision.language)
            await self._emit_switch(decision.language)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("LidTapProcessor identify task error: {}", exc)

    async def _emit_switch(self, language: str) -> None:
        # Push downstream from this tap (before STT) so switchers see the frame
        # without re-entering the pipeline head. Safe from the identify task
        # because push_frame only enqueues onto the next processor.
        frame = LanguageSwitchFrame(language=language)
        await self.push_frame(frame, FrameDirection.DOWNSTREAM)
        logger.info("LidTapProcessor pushed LanguageSwitchFrame language={}", language)

    async def _shutdown(self) -> None:
        self._closed = True
        self._user_speaking = False
        self._buffer.reset()
        tasks = list(self._identify_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._identify_tasks.clear()
        if self._owns_client:
            await self._client.aclose()
