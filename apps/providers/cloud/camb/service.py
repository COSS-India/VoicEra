"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_tts
from .config import CambTTSConfig


@register_tts
def create_tts(cfg: CambTTSConfig):
    from pipecat.services.camb.tts import CambTTSService, CambTTSSettings
    from pipecat.utils.types import NOT_GIVEN

    return CambTTSService(
        api_key=cfg.api_key,
        settings=CambTTSSettings(
            voice=int(cfg.voice),
            model=cfg.model,
            language=cfg.language,
            user_instructions=(
                cfg.user_instructions
                if cfg.model == "mars-instruct" and cfg.user_instructions
                else NOT_GIVEN
            ),
        ),
    )
