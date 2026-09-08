"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_stt
from .config import AssemblyAISTTConfig


@register_stt
def create_stt(cfg: AssemblyAISTTConfig):
    from pipecat.services.assemblyai.stt import (
        AssemblyAISTTService,
        AssemblyAISTTSettings,
    )

    return AssemblyAISTTService(
        api_key=cfg.api_key,
        settings=AssemblyAISTTSettings(model=cfg.model, language=cfg.language),
    )

