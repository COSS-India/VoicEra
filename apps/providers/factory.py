"""Create Pipecat STT / TTS / LLM services from agent provider configs.

Creators live next to each vendor (``cloud/*/service.py``,
``adapters/*/service.py``) and register into ``registry``. This module
builds discriminated unions from that registry and dispatches
``create_*_service``.

Usage::

    from apps.providers.factory import (
        AgentConfig,
        create_stt_service,
        create_tts_service,
        create_llm_service,
    )

    stt = create_stt_service(agent_config)
    tts = create_tts_service(agent_config)
    llm = create_llm_service(agent_config)
"""

from __future__ import annotations

from typing import Annotated, Any, Union

from loguru import logger
from pydantic import BaseModel, Field

from .base import Kind
from .registry import config_classes, get_creator, load_providers

# ---------------------------------------------------------------------------
# Discriminated config unions + AgentConfig (from registry)
# ---------------------------------------------------------------------------


def _union_type(kind: Kind):
    classes = config_classes(kind)
    if not classes:
        raise RuntimeError(
            f"No {kind.value} providers registered. "
            "Ensure vendor service.py modules are importable."
        )
    return Annotated[Union[classes], Field(discriminator="provider")]


# Ensure creators are registered before unions are built.
load_providers()

STTConfig = _union_type(Kind.STT)
TTSConfig = _union_type(Kind.TTS)
LLMConfig = _union_type(Kind.LLM)


class AgentConfig(BaseModel):
    """Top-level agent AI model configuration used by the service factory."""

    stt_config: STTConfig | None = None
    tts_config: TTSConfig | None = None
    llm_config: LLMConfig | None = None


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _require(config: Any, name: str) -> Any:
    if config is None:
        raise ValueError(f"AgentConfig.{name} is required")
    return config


def create_stt_service(agent_config: AgentConfig):
    """Create a Pipecat STT service from ``agent_config.stt_config``."""
    cfg = _require(agent_config.stt_config, "stt_config")
    logger.info(f"Creating STT service: provider={cfg.provider}, model={cfg.model}")
    return get_creator(Kind.STT, cfg.provider)(cfg)


def create_tts_service(agent_config: AgentConfig):
    """Create a Pipecat TTS service from ``agent_config.tts_config``."""
    cfg = _require(agent_config.tts_config, "tts_config")
    logger.info(f"Creating TTS service: provider={cfg.provider}, model={cfg.model}")
    return get_creator(Kind.TTS, cfg.provider)(cfg)


def create_llm_service(agent_config: AgentConfig):
    """Create a Pipecat LLM service from ``agent_config.llm_config``."""
    cfg = _require(agent_config.llm_config, "llm_config")
    logger.info(f"Creating LLM service: provider={cfg.provider}, model={cfg.model}")
    return get_creator(Kind.LLM, cfg.provider)(cfg)


__all__ = [
    "AgentConfig",
    "STTConfig",
    "TTSConfig",
    "LLMConfig",
    "create_stt_service",
    "create_tts_service",
    "create_llm_service",
]
