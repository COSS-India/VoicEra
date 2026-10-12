"""Build Pipecat services from Indic Transcribe configs."""

from __future__ import annotations

from ...availability import register_local
from ...registry import register_stt
from .catalog import GATEWAY_MODEL_ID, resolve_realtime_url, resolve_wire_language
from .config import IndicTranscribeSTTConfig

register_local("indic_transcribe", GATEWAY_MODEL_ID)


@register_stt
def create_stt(cfg: IndicTranscribeSTTConfig):
    from .stt import IndicTranscribeSTTService

    return IndicTranscribeSTTService(
        base_url=resolve_realtime_url(),
        model=cfg.model,
        language=resolve_wire_language(cfg.model, cfg.language),
    )
