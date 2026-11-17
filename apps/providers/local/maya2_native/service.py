"""Build a Pipecat TTS service from Maya 2 Native config."""

from __future__ import annotations

from ...availability import register_local
from ...registry import register_tts
from .catalog import (
    GATEWAY_MODEL_ID,
    SAMPLE_RATE,
    resolve_base_url,
    resolve_wire_language,
)
from .config import Maya2NativeTTSConfig

register_local("maya2_native", GATEWAY_MODEL_ID)


@register_tts
def create_tts(cfg: Maya2NativeTTSConfig):
    from .tts import Maya2NativeTTSService

    # Gateway has no auth; OpenAI SDK still requires a non-empty key string.
    return Maya2NativeTTSService(
        api_key="not-needed",
        base_url=resolve_base_url(),
        model=cfg.model,
        voice=cfg.voice,
        language=resolve_wire_language(cfg.language),
        sample_rate=SAMPLE_RATE,
    )
