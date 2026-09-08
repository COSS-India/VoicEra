"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_stt
from .config import GladiaSTTConfig


@register_stt
def create_stt(cfg: GladiaSTTConfig):
    from pipecat.services.gladia.config import LanguageConfig
    from pipecat.services.gladia.stt import GladiaSTTService, GladiaSTTSettings

    return GladiaSTTService(
        api_key=cfg.api_key,
        settings=GladiaSTTSettings(
            model=cfg.model,
            language_config=LanguageConfig(languages=[cfg.language]),
        ),
    )

