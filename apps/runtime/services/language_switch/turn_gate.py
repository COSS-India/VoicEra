"""Hold main-ASR finals while Nemotron + IndicLID judge the utterance's language."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    TranscriptionFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.utils.time import time_now_iso8601

from apps.runtime.services.language_switch.frames import (
    LanguageSwitchFrame,
    NemotronTranscriptFrame,
)
from apps.runtime.services.language_switch.lid.indiclid import IndicLidClient
from apps.runtime.services.language_switch.lid.judge import (
    JudgeDecision,
    LanguageJudge,
    normalise_language,
)


class LidTurnGate(FrameProcessor):
    """Sits between STT and the user aggregator.

    Main-ASR finals are held from speech start. After speech stops the gate
    waits for the Nemotron transcript (``NemotronTranscriptFrame``) and for a
    main final, or ``hold_deadline_s``, then runs the judge in the background
    (audio keeps flowing meanwhile):

    * stay, or any failure — release the held main finals;
    * switch — drop the main text, speak the handoff message of the language being
      left, broadcast ``LanguageSwitchFrame`` (so the STT switcher upstream and the
      LLM/TTS switchers downstream all flip), then push the chosen transcript as
      the turn's final. Late finals from the old STT are dropped until the next
      speech start.

    The handoff message belongs to the language being left and is spoken by that
    language's own TTS: it is queued *ahead of* the switch frame, so the TTS
    switcher is still on the old service when it arrives, and the old service
    finishes it after the switch (the switcher only gates what enters a service,
    not what it emits). The LLM is handed the turn straight away, so the message,
    the language change and the first reply tokens overlap instead of adding up.
    The message is not added to the LLM context.

    VAD frames reach this processor upstream from the aggregator; they are only
    observed, never held.
    """

    def __init__(
        self,
        *,
        judge: LanguageJudge,
        client: IndicLidClient,
        hold_deadline_s: float,
        handoff_messages: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._judge = judge
        self._client = client
        self._hold_deadline_s = hold_deadline_s
        self._handoff_messages = {
            normalise_language(language): message.strip()
            for language, message in (handoff_messages or {}).items()
            if normalise_language(language) and (message or "").strip()
        }
        self._speaking = False
        self._awaiting = False  # speech ended, language not yet judged
        self._suppressing = False
        self._nemotron: str | None = None
        self._held: list[TranscriptionFrame] = []
        self._deadline: asyncio.Task[None] | None = None
        self._resolve_task: asyncio.Task[None] | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, (EndFrame, CancelFrame)):
            await self._shutdown()
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            await self._on_speech_started()
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._on_speech_stopped()
        elif direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, NemotronTranscriptFrame):
                if self._awaiting and self._nemotron is None:
                    self._nemotron = frame.text
                    self._maybe_resolve()
                return  # never forwarded; stale ones are ignored
            if isinstance(frame, TranscriptionFrame):
                if self._suppressing:
                    logger.debug("LidTurnGate dropped old-STT final after switch")
                elif self._speaking or self._awaiting:
                    self._held.append(frame)
                    self._maybe_resolve()
                else:
                    await self.push_frame(frame, direction)
                return

        await self.push_frame(frame, direction)

    async def _on_speech_started(self) -> None:
        await self._cancel_tasks()
        self._speaking = True
        self._awaiting = False
        self._suppressing = False
        self._nemotron = None

    def _on_speech_stopped(self) -> None:
        if not self._speaking:
            return
        self._speaking = False
        self._awaiting = True
        self._nemotron = None
        self._deadline = asyncio.create_task(self._expire())

    async def _expire(self) -> None:
        await asyncio.sleep(self._hold_deadline_s)
        self._deadline = None
        logger.info("LidTurnGate hold deadline reached")
        self._maybe_resolve(force=True)

    def _maybe_resolve(self, *, force: bool = False) -> None:
        if not self._awaiting or self._resolve_task is not None:
            return
        if not force and (self._nemotron is None or not self._held):
            return
        self._resolve_task = asyncio.create_task(self._resolve())

    async def _resolve(self) -> None:
        decision: JudgeDecision | None = None
        try:
            main = self._judge.usable(
                " ".join(f.text.strip() for f in self._held if f.text.strip())
            )
            nemotron = self._judge.usable(self._nemotron or "")
            if main or nemotron:
                main_ev, nemotron_ev = await self._client.score([main, nemotron])
                decision = self._judge.decide(main_ev, nemotron_ev)
                self._log(decision)
        except asyncio.CancelledError:
            return  # new speech: keep holding, the next utterance resolves
        except Exception as exc:
            logger.warning("LidTurnGate judge error: {}", exc)
        await self._finish(decision)

    async def _finish(self, decision: JudgeDecision | None) -> None:
        held, self._held = self._held, []
        self._awaiting = False
        self._nemotron = None
        self._resolve_task = None
        if self._deadline is not None:
            self._deadline.cancel()
            self._deadline = None

        if decision is not None and decision.outcome == "switch" and decision.text:
            self._suppressing = True
            message = self._handoff_messages.get(normalise_language(decision.previous_language))
            if message:
                # Ahead of the switch frame: it must reach the old TTS.
                await self.push_frame(
                    TTSSpeakFrame(message, append_to_context=False),
                    FrameDirection.DOWNSTREAM,
                )
            await self.broadcast_frame(LanguageSwitchFrame, language=decision.language)
            await self.push_frame(
                TranscriptionFrame(
                    text=decision.text,
                    user_id="",
                    timestamp=time_now_iso8601(),
                    finalized=True,
                ),
                FrameDirection.DOWNSTREAM,
            )
            return
        for frame in held:
            await self.push_frame(frame, FrameDirection.DOWNSTREAM)

    @staticmethod
    def _log(decision: JudgeDecision) -> None:
        evidence = {
            name: None
            if item is None
            else {
                "script": item.script,
                "scores": item.scores,
                "other": round(item.other_mass, 3),
                "top": f"{item.top_label}:{item.top_score:.2f}",
            }
            for name, item in decision.evidence.items()
        }
        logger.info(
            "LidTurnGate decision={} language={} reason={} source={} scores={} evidence={}",
            decision.outcome,
            decision.language,
            decision.reason,
            decision.text_source,
            decision.scores,
            evidence,
        )

    async def _cancel_tasks(self) -> None:
        tasks = [t for t in (self._deadline, self._resolve_task) if t is not None]
        self._deadline = self._resolve_task = None
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _shutdown(self) -> None:
        self._held.clear()
        await self._cancel_tasks()
        await self._client.aclose()
