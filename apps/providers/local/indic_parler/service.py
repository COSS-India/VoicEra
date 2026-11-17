"""Build a Pipecat TTS service from Indic Parler config."""

from __future__ import annotations

from ...availability import register_local
from ...registry import register_tts
from .catalog import GATEWAY_MODEL_ID, SAMPLE_RATE, resolve_base_url
from .config import IndicParlerTTSConfig

register_local("indic_parler", GATEWAY_MODEL_ID)


@register_tts
def create_tts(cfg: IndicParlerTTSConfig):
    from .tts import IndicParlerTTSService

    # Gateway has no auth; OpenAI SDK still requires a non-empty key string.
    return IndicParlerTTSService(
        api_key="not-needed",
        base_url=resolve_base_url(),
        model=cfg.model,
        voice=cfg.voice,
        style=cfg.style,
        sample_rate=SAMPLE_RATE,
    )
