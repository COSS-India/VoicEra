"""Build Pipecat TTS service from Portuguese Chatterbox config."""

from __future__ import annotations

from ...availability import register_local
from ...registry import register_tts
from .catalog import GATEWAY_MODEL_ID, SAMPLE_RATE, resolve_base_url
from .config import PtChatterboxTTSConfig

register_local("pt_chatterbox", GATEWAY_MODEL_ID)


@register_tts
def create_tts(cfg: PtChatterboxTTSConfig):
    from .tts import PtChatterboxTTSService

    # Gateway has no auth; OpenAI SDK still requires a non-empty key string.
    return PtChatterboxTTSService(
        api_key="not-needed",
        base_url=resolve_base_url(),
        model=cfg.model,
        voice=cfg.voice,
        sample_rate=SAMPLE_RATE,
    )
