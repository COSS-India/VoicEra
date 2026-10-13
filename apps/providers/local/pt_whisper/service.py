"""Build Pipecat services from Portuguese Whisper configs."""

from __future__ import annotations

from ...availability import register_local
from ...registry import register_stt
from .catalog import GATEWAY_MODEL_ID, resolve_wire_language, resolve_ws_url
from .config import PtWhisperSTTConfig

register_local("pt_whisper", GATEWAY_MODEL_ID)


@register_stt
def create_stt(cfg: PtWhisperSTTConfig):
    from .stt import PtWhisperSTTService

    return PtWhisperSTTService(
        ws_url=resolve_ws_url(),
        language=resolve_wire_language(cfg.model, cfg.language),
    )
