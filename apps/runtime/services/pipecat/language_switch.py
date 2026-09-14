"""Central mid-call language switching via Pipecat runtime update frames.

Architecture::

                    ┌── DLS tool call (this module)
                    │
    LanguageSwitcher┤
                    │
                    └── ALD (future)

The LLM tool only receives a language id. Saved ``language_models`` is the
source of truth for STT/TTS/LLM/voice settings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    LLMUpdateSettingsFrame,
    STTUpdateSettingsFrame,
    TTSUpdateSettingsFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.settings import LLMSettings, STTSettings, TTSSettings

from apps.runtime.services.ai_service_factory import (
    configured_language_ids,
    resolve_language_models,
)
from apps.runtime.services.pipecat.call_ending import _append_tools


# Runtime-updatable fields only — never constructor secrets (api_key, etc.).
_STT_RUNTIME_KEYS = frozenset({"language", "model"})
_TTS_RUNTIME_KEYS = frozenset({"language", "voice", "model", "speed", "volume"})
_LLM_RUNTIME_KEYS = frozenset(
    {
        "model",
        "temperature",
        "max_tokens",
        "top_p",
        "top_k",
        "frequency_penalty",
        "presence_penalty",
        "seed",
    }
)


def extract_stt_runtime_settings(stt_config: dict[str, Any]) -> dict[str, Any]:
    return {k: stt_config[k] for k in _STT_RUNTIME_KEYS if k in stt_config and stt_config[k] is not None}


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
    return {k: llm_config[k] for k in _LLM_RUNTIME_KEYS if k in llm_config and llm_config[k] is not None}


def _provider(cfg: dict[str, Any] | None) -> str:
    if not isinstance(cfg, dict):
        return ""
    return str(cfg.get("provider") or "").strip()


@dataclass
class LanguageSwitcher:
    """Lookup ``language_models[lang]`` and queue Pipecat update frames."""

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

    async def switch(self, language: str) -> dict[str, Any]:
        """Switch the active call to ``language`` if configured.

        Returns a tool-result dict describing success or rejection. Never
        silently falls back to another language.
        """
        requested = (language or "").strip()
        if not requested:
            return {
                "status": "error",
                "error": "language is required",
                "active_language": self.active_language,
                "configured_languages": self.configured_languages,
            }

        if requested not in self.language_models:
            logger.warning(
                "Language switch rejected: {} not in {}",
                requested,
                sorted(self.language_models),
            )
            return {
                "status": "error",
                "error": f"language {requested!r} is not configured for this agent",
                "active_language": self.active_language,
                "configured_languages": self.configured_languages,
            }

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
                return {
                    "status": "error",
                    "error": (
                        f"cannot switch to {requested!r}: {kind} provider changes "
                        f"from {cur_p!r} to {new_p!r} (runtime provider swap unsupported)"
                    ),
                    "active_language": self.active_language,
                    "configured_languages": self.configured_languages,
                }

        stt_settings = extract_stt_runtime_settings(target.get("stt_config") or {})
        tts_settings = extract_tts_runtime_settings(target.get("tts_config") or {})
        llm_settings = extract_llm_runtime_settings(target.get("llm_config") or {})

        # Order: STT first (next user utterance), then TTS (next bot speech),
        # then LLM. STT is upstream of the LLM; TTS is downstream. LLM settings
        # are applied directly — a DOWNSTREAM frame would skip this service.
        if stt_settings:
            await self.llm.push_frame(
                STTUpdateSettingsFrame(delta=STTSettings(**stt_settings)),
                FrameDirection.UPSTREAM,
            )
        if tts_settings:
            await self.llm.push_frame(
                self._tts_update_frame(tts_settings),
                FrameDirection.DOWNSTREAM,
            )
        if llm_settings:
            delta = LLMSettings(**llm_settings)
            if hasattr(self.llm, "_update_settings"):
                await self.llm._update_settings(delta)
            else:
                await self.llm.push_frame(
                    LLMUpdateSettingsFrame(delta=delta),
                    FrameDirection.DOWNSTREAM,
                )

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


def build_language_switcher(
    agent: dict[str, Any],
    *,
    llm: Any,
    language_models: dict[str, dict[str, Any]] | None = None,
) -> LanguageSwitcher | None:
    """Build a switcher when the agent has more than one configured language.

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
    return LanguageSwitcher(
        language_models={lang: stacks[lang] for lang in allowed},
        active_language=primary,
        llm=llm,
        allowed_languages=allowed,
    )


def configure_language_switching(
    agent: dict[str, Any],
    *,
    context: LLMContext,
    llm: Any,
    language_models: dict[str, dict[str, Any]] | None = None,
) -> LanguageSwitcher | None:
    """Register the ``switch_language`` DLS tool when multi-language is configured."""
    switcher = build_language_switcher(
        agent, llm=llm, language_models=language_models
    )
    if switcher is None:
        return None

    async def switch_language(params: FunctionCallParams, language: str) -> None:
        """Switch the active call language.

        Call this when the user asks to speak in another configured language
        (for example Hindi, Kannada, Malayalam). Only pass the language id —
        never model, voice, or provider settings.

        Args:
            language: Canonical language id such as ``hi``, ``kn``, ``ml``, ``en``.
        """
        result = await switcher.switch(language)
        await params.result_callback(result)

    _append_tools(context, [switch_language])
    logger.info(
        "Language switching enabled agent_id={} languages={}",
        agent.get("agent_id"),
        switcher.configured_languages,
    )
    return switcher
