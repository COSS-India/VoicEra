"""Language-aware service switchers for STT/TTS/LLM."""

from __future__ import annotations

import asyncio
from typing import Any, Literal, cast

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    LLMContextFrame,
    LLMUpdateSettingsFrame,
    ManuallySwitchServiceFrame,
    STTUpdateSettingsFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
    TTSUpdateSettingsFrame,
)
from pipecat.pipeline.llm_switcher import LLMSwitcher
from pipecat.pipeline.service_switcher import (
    ServiceSwitcher,
    ServiceSwitcherStrategyManual,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService

from apps.runtime.services.language_switch.frames import LanguageSwitchFrame
from apps.runtime.services.language_switch.routes import LanguageRoute

ServiceKind = Literal["stt", "tts", "llm"]

# Longest a language switch waits for a queued handoff message to finish
# synthesising. Synthesis takes a few hundred ms; this only bounds a service
# that never reports it.
HANDOFF_SYNTH_WAIT_S = 3.0


class _LanguageRoutingMixin:
    """Shared language-route apply logic for STT/TTS/LLM switchers."""

    _kind: ServiceKind
    _routes: dict[str, LanguageRoute]
    _active_lang: str

    @property
    def active_language(self) -> str:
        return self._active_lang

    async def apply_language(self, language: str) -> bool:
        """Make ``language`` active. True if active afterwards; False if unknown/failed."""
        lang = (language or "").strip()
        if not lang or lang not in self._routes:
            return False
        if lang == self._active_lang:
            return True

        route = self._routes[lang]
        active = self.strategy.active_service  # type: ignore[attr-defined]
        if route.service is not active:
            switched = await self.strategy.handle_frame(  # type: ignore[attr-defined]
                ManuallySwitchServiceFrame(service=route.service),
                FrameDirection.DOWNSTREAM,
            )
            if switched is None:
                logger.warning(
                    "{} failed to switch to {} for language {}",
                    self.name,  # type: ignore[attr-defined]
                    route.service.name,
                    lang,
                )
                return False

        update = self._update_frame(route)
        await route.service.process_frame(update, FrameDirection.DOWNSTREAM)
        self._active_lang = lang
        await self._after_language_applied(lang)
        logger.info("{} active language -> {}", self.name, lang)  # type: ignore[attr-defined]
        return True

    async def _after_language_applied(self, language: str) -> None:
        """Hook for subclasses (e.g. LLM tool-handler sync)."""

    def _update_frame(self, route: LanguageRoute) -> Any:
        if self._kind == "stt":
            return STTUpdateSettingsFrame(
                service=route.service,
                delta=route.settings_delta,
            )
        if self._kind == "tts":
            return TTSUpdateSettingsFrame(
                service=route.service,
                delta=route.settings_delta,
            )
        return LLMUpdateSettingsFrame(
            service=route.service,
            delta=route.settings_delta,
        )


class ModelServiceSwitcher(_LanguageRoutingMixin, ServiceSwitcher):
    """Switch or reconfigure pooled STT/TTS services on language change.

    A TTS language switch can follow a handoff message (``TTSSpeakFrame`` with
    ``append_to_context=False``) for the language being left. That message is
    synthesised by the current voice, and the voice reads its settings when it
    starts a message. So the switch waits for the message's ``TTSStoppedFrame``
    before applying the new settings. The LLM is not blocked by this: its text
    reaches this switcher only after the switch has been handled.
    """

    def __init__(
        self,
        *,
        kind: Literal["stt", "tts"],
        services: list[Any],
        routes: dict[str, LanguageRoute],
        primary_language: str,
    ) -> None:
        super().__init__(services, strategy_type=ServiceSwitcherStrategyManual)
        self._kind = kind
        self._routes = routes
        self._active_lang = primary_language
        self._handoff_inflight = False
        self._handoff_done = asyncio.Event()

    async def process_frame(self, frame: Any, direction: FrameDirection) -> None:
        if isinstance(frame, LanguageSwitchFrame):
            await self._await_handoff_synthesis()
            await self.apply_language(frame.language)
            await self.push_frame(frame, direction)
            return
        if (
            self._kind == "tts"
            and isinstance(frame, TTSSpeakFrame)
            and not frame.append_to_context
        ):
            self._handoff_done.clear()
            self._handoff_inflight = True
        await super().process_frame(frame, direction)

    async def push_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        # Output from the member services. The first stop after a handoff is that handoff's.
        if self._handoff_inflight and isinstance(frame, TTSStoppedFrame):
            self._handoff_inflight = False
            self._handoff_done.set()
        await super().push_frame(frame, direction)

    async def _await_handoff_synthesis(self) -> None:
        if not self._handoff_inflight:
            return
        try:
            await asyncio.wait_for(self._handoff_done.wait(), timeout=HANDOFF_SYNTH_WAIT_S)
        except asyncio.TimeoutError:
            logger.warning(
                "{} handoff message not synthesised within {}s; switching anyway",
                self.name,
                HANDOFF_SYNTH_WAIT_S,
            )
        self._handoff_inflight = False


class ModelLLMSwitcher(_LanguageRoutingMixin, LLMSwitcher):
    """LLM switcher with language routes and tool-handler sync across members."""

    def __init__(
        self,
        *,
        services: list[Any],
        routes: dict[str, LanguageRoute],
        primary_language: str,
        context: LLMContext | None = None,
    ) -> None:
        super().__init__(
            llms=cast(list[LLMService], services),
            strategy_type=ServiceSwitcherStrategyManual,
        )
        self._kind = "llm"
        self._routes = routes
        self._active_lang = primary_language
        self._context = context

    def bind_context(self, context: LLMContext) -> None:
        """Attach the session LLMContext so tools stay synced after language switches."""
        self._context = context
        self._sync_registered_tool_handlers(context.tools)

    def _sync_registered_tool_handlers(self, tools: Any) -> None:
        """Ask each LLM member to sync handlers for the context tool schema."""
        for llm in self.services:  # type: ignore[attr-defined]
            sync = getattr(llm, "_sync_registered_tool_handlers", None)
            if callable(sync):
                sync(tools)

    async def _after_language_applied(self, language: str) -> None:
        del language
        if self._context is not None:
            self._sync_registered_tool_handlers(self._context.tools)

    async def process_frame(self, frame: Any, direction: FrameDirection) -> None:
        if isinstance(frame, LanguageSwitchFrame):
            await self.apply_language(frame.language)
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, LLMContextFrame):
            self._sync_registered_tool_handlers(frame.context.tools)
        await super().process_frame(frame, direction)
