"""ModelServiceSwitcher — deduped services with language-aware routing."""

from __future__ import annotations

from typing import Any, Literal

from loguru import logger
from pipecat.frames.frames import (
    LLMUpdateSettingsFrame,
    ManuallySwitchServiceFrame,
    STTUpdateSettingsFrame,
    TTSUpdateSettingsFrame,
)
from pipecat.pipeline.service_switcher import (
    ServiceSwitcher,
    ServiceSwitcherStrategyManual,
)
from pipecat.processors.frame_processor import FrameDirection

from apps.runtime.services.language_switch.frames import LanguageSwitchFrame
from apps.runtime.services.language_switch.routes import LanguageRoute

ServiceKind = Literal["stt", "tts", "llm"]


class ModelServiceSwitcher(ServiceSwitcher):
    """Switch or reconfigure pooled STT/TTS/LLM services on language change."""

    def __init__(
        self,
        *,
        kind: ServiceKind,
        services: list[Any],
        routes: dict[str, LanguageRoute],
        primary_language: str,
    ) -> None:
        super().__init__(services, strategy_type=ServiceSwitcherStrategyManual)
        self._kind = kind
        self._routes = routes
        self._active_lang = primary_language

    @property
    def active_language(self) -> str:
        return self._active_lang

    async def apply_language(self, language: str) -> bool:
        """Switch to ``language`` if configured. Returns True when applied."""
        lang = (language or "").strip()
        if not lang or lang == self._active_lang or lang not in self._routes:
            return False

        route = self._routes[lang]
        active = self.strategy.active_service
        if route.service is not active:
            switched = await self.strategy.handle_frame(
                ManuallySwitchServiceFrame(service=route.service),
                FrameDirection.DOWNSTREAM,
            )
            if switched is None:
                logger.warning(
                    "{} failed to switch to {} for language {}",
                    self.name,
                    route.service.name,
                    lang,
                )
                return False

        update = self._update_frame(route)
        await route.service.process_frame(update, FrameDirection.DOWNSTREAM)
        self._active_lang = lang
        logger.info("{} active language -> {}", self.name, lang)
        return True

    async def process_frame(self, frame: Any, direction: FrameDirection) -> None:
        if isinstance(frame, LanguageSwitchFrame):
            await self.apply_language(frame.language)
            return
        await super().process_frame(frame, direction)

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
