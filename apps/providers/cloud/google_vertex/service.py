"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_llm, llm_settings
from .config import GoogleVertexLLMConfig


@register_llm
def create_llm(cfg: GoogleVertexLLMConfig):
    from pipecat.services.google.vertex.llm import (
        GoogleVertexLLMService,
        GoogleVertexLLMSettings,
    )

    return GoogleVertexLLMService(
        credentials=cfg.credentials,
        project_id=cfg.project_id,
        location=cfg.location,
        settings=GoogleVertexLLMSettings(**llm_settings(cfg)),
    )

