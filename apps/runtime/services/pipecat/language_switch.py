"""Mid-call language switching: DLS tool emits a frame; the processor applies it.

Architecture::

    register_language_switching_tool()
            │
            ├── register switch_language DLS tool
            │
            └── return LanguageSwitchProcessor

    switch_language("kn")
            ↓
    validate "kn"
            ↓
    LanguageSwitchFrame("kn")   (broadcast from the LLM both ways)
            ↓
    LanguageSwitchProcessor     (downstream; consumes the frame)
            ↓
    LanguageSwitcher.switch()   (existing STT/TTS/LLM runtime updates)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    LLMUpdateSettingsFrame,
    STTUpdateSettingsFrame,
    TTSUpdateSettingsFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.settings import LLMSettings, STTSettings, TTSSettings

from apps.runtime.services.ai_service_factory import (
    configured_language_ids,
    resolve_language_models,
)
from apps.runtime.services.pipecat.call_ending import _append_tools
from apps.runtime.services.pipecat.frames import LanguageSwitchFrame


# ---------------------------------------------------------------------------
# Constants — runtime-updatable fields only (never constructor secrets)
# ---------------------------------------------------------------------------

_STT_RUNTIME_KEYS = frozenset({
    "language",
    "model",
})

_TTS_RUNTIME_KEYS = frozenset({
    "language",
    "voice",
    "model",
    "speed",
    "volume",
})

_LLM_RUNTIME_KEYS = frozenset({
    "model",
    "temperature",
    "max_tokens",
    "top_p",
    "top_k",
    "frequency_penalty",
    "presence_penalty",
    "seed",
})


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def extract_stt_runtime_settings(stt_config: dict[str, Any]) -> dict[str, Any]:
    return {
        k: stt_config[k]
        for k in _STT_RUNTIME_KEYS
        if k in stt_config and stt_config[k] is not None
    }


def extract_tts_runtime_settings(tts_config: dict[str, Any]) -> dict[str, Any]:
    out = {
        k: tts_config[k]
        for k in ("language", "voice", "model")
        if k in tts_config and tts_config[k] is not None
    }
    # Cartesia (and similar) store speed/volume as top-level config fields that
    # map into provider-specific generation settings via from_mapping / extra.
    for key in ("speed", "volume"):
        if key in tts_config and tts_config[key] is not None:
            out[key] = tts_config[key]
    return out


def extract_llm_runtime_settings(llm_config: dict[str, Any]) -> dict[str, Any]:
    return {
        k: llm_config[k]
        for k in _LLM_RUNTIME_KEYS
        if k in llm_config and llm_config[k] is not None
    }


def _provider(cfg: dict[str, Any] | None) -> str:
    if not isinstance(cfg, dict):
        return ""
    return str(cfg.get("provider") or "").strip()


# ---------------------------------------------------------------------------
# Runtime classes
# ---------------------------------------------------------------------------

@dataclass
class LanguageSwitcher:
    """Owns language state and applies existing STT/TTS/LLM runtime updates."""

    language_models: dict[str, dict[str, Any]]
    active_language: str
    llm: Any
    allowed_languages: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.allowed_languages:
            self.allowed_languages = list(self.language_models.keys())
        if self.active_language not in self.language_models:
            raise ValueError(
                f"active_language {self.active_language!r} not in language_models"
            )

    @property
    def configured_languages(self) -> list[str]:
        return list(self.allowed_languages)

    def stack_for(self, language: str) -> dict[str, Any] | None:
        return self.language_models.get(language)

    def _error_result(self, error: str) -> dict[str, Any]:
        return {
            "status": "error",
            "error": error,
            "active_language": self.active_language,
            "configured_languages": self.configured_languages,
        }

    def availability_error(self, language: str) -> dict[str, Any] | None:
        requested = (language or "").strip()
        if not requested:
            return self._error_result("language is required")
        if requested not in self.language_models:
            logger.warning(
                "Language switch rejected: {} not in {}",
                requested,
                sorted(self.language_models),
            )
            return self._error_result(
                f"language {requested!r} is not configured for this agent"
            )
        return None

    async def switch(self, language: str, *, pusher: Any) -> dict[str, Any]:
        """Switch the active call to ``language`` if configured.

        ``pusher`` is the pipeline origin for update frames (the processor).
        ``active_language`` is updated only after STT/TTS/LLM updates succeed.
        """
        error = self.availability_error(language)
        if error is not None:
            return error

        requested = language.strip()
        if requested == self.active_language:
            return {
                "status": "ok",
                "active_language": self.active_language,
                "message": f"already using language {requested!r}",
            }

        current = self.language_models[self.active_language]
        target = self.language_models[requested]

        # Same public API regardless of provider — but swapping providers mid-call
        # cannot be done via UpdateSettings frames alone.
        for kind in ("stt_config", "tts_config", "llm_config"):
            cur_p = _provider(current.get(kind))
            new_p = _provider(target.get(kind))
            if cur_p and new_p and cur_p != new_p:
                logger.warning(
                    "Language switch rejected: {} provider change {} → {} for {}",
                    requested,
                    cur_p,
                    new_p,
                    kind,
                )
                return self._error_result(
                    f"cannot switch to {requested!r}: {kind} provider changes "
                    f"from {cur_p!r} to {new_p!r} (runtime provider swap unsupported)"
                )

        stt_settings = extract_stt_runtime_settings(target.get("stt_config") or {})
        tts_settings = extract_tts_runtime_settings(target.get("tts_config") or {})
        llm_settings = extract_llm_runtime_settings(target.get("llm_config") or {})

        # Origin is the processor (after the LLM):
        # STT is upstream, TTS is downstream. LLM settings are applied on the
        # LLM instance — a downstream LLMUpdateSettingsFrame would skip it.
        try:
            if stt_settings:
                await pusher.push_frame(
                    STTUpdateSettingsFrame(delta=STTSettings(**stt_settings)),
                    FrameDirection.UPSTREAM,
                )
            if tts_settings:
                await pusher.push_frame(
                    self._tts_update_frame(tts_settings),
                    FrameDirection.DOWNSTREAM,
                )
            if llm_settings:
                delta = LLMSettings(**llm_settings)
                if hasattr(self.llm, "_update_settings"):
                    await self.llm._update_settings(delta)
                else:
                    await pusher.push_frame(
                        LLMUpdateSettingsFrame(delta=delta),
                        FrameDirection.UPSTREAM,
                    )
        except Exception:
            logger.exception("Language switch failed for {}", requested)
            return self._error_result(f"failed to switch to {requested!r}")

        previous = self.active_language
        self.active_language = requested
        voice = (target.get("tts_config") or {}).get("voice")
        logger.info(
            "Language switched {} → {} voice={}",
            previous,
            requested,
            voice,
        )
        return {
            "status": "ok",
            "previous_language": previous,
            "active_language": requested,
            "voice": voice,
        }

    @staticmethod
    def _tts_update_frame(tts_settings: dict[str, Any]) -> TTSUpdateSettingsFrame:
        """Build a TTS update frame from runtime-updatable config fields.

        Only ``language`` / ``voice`` / ``model`` are applied via typed
        :class:`TTSSettings`. Speed/volume are intentionally omitted: Cartesia
        stores them on ``GenerationConfig``, and passing a plain dict through
        ``TTSUpdateSettingsFrame(settings=...)`` leaves ``generation_config`` as
        a dict that later crashes with ``'dict' object has no attribute
        'model_dump'``. Per-language speed/volume rarely differ in our UI.
        """
        core = {
            k: tts_settings[k]
            for k in ("language", "voice", "model")
            if k in tts_settings
        }
        return TTSUpdateSettingsFrame(delta=TTSSettings(**core))


class LanguageSwitchProcessor(FrameProcessor):
    """Pipecat adapter: receives ``LanguageSwitchFrame``, delegates to LanguageSwitcher.

    Placed immediately after the LLM. Downstream copies of the frame are
    consumed here (not forwarded to TTS). Upstream copies are ignored by
    processors that do not handle this frame type.
    """

    def __init__(
        self,
        *,
        language_models: dict[str, dict[str, Any]],
        active_language: str,
        llm: Any,
        allowed_languages: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.llm = llm
        self._switcher = LanguageSwitcher(
            language_models=language_models,
            active_language=active_language,
            llm=llm,
            allowed_languages=list(allowed_languages or language_models.keys()),
        )

    @property
    def language_models(self) -> dict[str, dict[str, Any]]:
        return self._switcher.language_models

    @property
    def allowed_languages(self) -> list[str]:
        return self._switcher.allowed_languages

    @property
    def configured_languages(self) -> list[str]:
        return self._switcher.configured_languages

    @property
    def active_language(self) -> str:
        return self._switcher.active_language

    @active_language.setter
    def active_language(self, value: str) -> None:
        self._switcher.active_language = value

    def stack_for(self, language: str) -> dict[str, Any] | None:
        return self._switcher.stack_for(language)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LanguageSwitchFrame):
            await self._switcher.switch(frame.language, pusher=self)
            return
        await self.push_frame(frame, direction)

    async def switch(self, language: str) -> dict[str, Any]:
        return await self._switcher.switch(language, pusher=self)

    async def switch_language(self, params: FunctionCallParams, language: str) -> None:
        """DLS tool: validate language and broadcast ``LanguageSwitchFrame``.

        Call this when the user asks to speak in another configured language
        (for example Hindi, Kannada, Malayalam). Only pass the language id —
        never model, voice, or provider settings.

        Args:
            language: Canonical language id such as ``hi``, ``kn``, ``ml``, ``en``.
        """
        error = self._switcher.availability_error(language)
        if error is not None:
            await params.result_callback(error)
            return

        requested = language.strip()
        await params.llm.broadcast_frame(LanguageSwitchFrame, language=requested)
        await params.result_callback(
            {
                "status": "ok",
                "requested_language": requested,
                "message": f"switching to language {requested!r}",
            }
        )


# ---------------------------------------------------------------------------
# Public registration
# ---------------------------------------------------------------------------

def build_language_switcher(
    agent: dict[str, Any],
    *,
    llm: Any,
    language_models: dict[str, dict[str, Any]] | None = None,
) -> LanguageSwitchProcessor | None:
    """Build a processor when the agent has more than one configured language.

    ``language_models`` should already be auth-merged when provided by the
    pipeline. If omitted, secrets-free configs from the agent payload are used
    (fine for unit tests; production should pass merged stacks).
    """
    config = agent.get("config") or {}
    stacks = language_models or resolve_language_models(config)
    allowed = configured_language_ids(config)
    # Only languages that both appear in language.* and have a stack entry.
    allowed = [lang for lang in allowed if lang in stacks]
    if len(allowed) < 2:
        return None

    primary = allowed[0]
    return LanguageSwitchProcessor(
        language_models={lang: stacks[lang] for lang in allowed},
        active_language=primary,
        llm=llm,
        allowed_languages=allowed,
    )


def register_language_switching_tool(
    agent: dict[str, Any],
    *,
    context: LLMContext,
    llm: Any,
    language_models: dict[str, dict[str, Any]] | None = None,
) -> LanguageSwitchProcessor | None:
    """Build the processor, register the DLS tool, and return the processor."""
    processor = build_language_switcher(
        agent, llm=llm, language_models=language_models
    )
    if processor is None:
        return None

    _append_tools(context, [processor.switch_language])
    logger.info(
        "Language switching enabled agent_id={} languages={}",
        agent.get("agent_id"),
        processor.configured_languages,
    )
    return processor
