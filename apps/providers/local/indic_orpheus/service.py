"""Build Pipecat TTS service from Indic Orpheus config."""

from __future__ import annotations

from ...availability import register_local
from ...registry import register_tts
from .catalog import GATEWAY_MODEL_ID, SAMPLE_RATE, resolve_base_url
from .config import IndicOrpheusTTSConfig

register_local("indic_orpheus", GATEWAY_MODEL_ID)


@register_tts
def create_tts(cfg: IndicOrpheusTTSConfig):
    from .tts import IndicOrpheusTTSService

    # Gateway has no auth; OpenAI SDK still requires a non-empty key string.
    return IndicOrpheusTTSService(
        api_key="not-needed",
        base_url=resolve_base_url(),
        model=cfg.model,
        voice=cfg.voice,
        style=cfg.style,
        sample_rate=SAMPLE_RATE,
    )
