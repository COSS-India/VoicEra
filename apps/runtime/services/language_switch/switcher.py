"""Language-aware service switchers for STT/TTS/LLM."""

from __future__ import annotations

from typing import Any, Literal, cast

from loguru import logger
from pipecat.frames.frames import (
    LLMUpdateSettingsFrame,
    ManuallySwitchServiceFrame,
    STTUpdateSettingsFrame,
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
    """Switch or reconfigure pooled STT/TTS services on language change."""

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

    async def process_frame(self, frame: Any, direction: FrameDirection) -> None:
        if isinstance(frame, LanguageSwitchFrame):
            await self.apply_language(frame.language)
            await self.push_frame(frame, direction)
            return
        await super().process_frame(frame, direction)


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

    async def _after_language_applied(self, language: str) -> None:
        if self._context is not None:
            self._sync_registered_tool_handlers(self._context.tools)

    async def process_frame(self, frame: Any, direction: FrameDirection) -> None:
        if isinstance(frame, LanguageSwitchFrame):
            await self.apply_language(frame.language)
            await self.push_frame(frame, direction)
            return
        # LLMSwitcher.process_frame syncs tools on LLMContextFrame to all members.
        await super().process_frame(frame, direction)
