"""Build Pipecat services from Hima-ASR configs."""

from __future__ import annotations

from ...availability import register_local
from ...registry import register_stt
from .catalog import GATEWAY_MODEL_ID, resolve_realtime_url, resolve_wire_language
from .config import HimaASRSTTConfig

register_local("hima_asr", GATEWAY_MODEL_ID)


@register_stt
def create_stt(cfg: HimaASRSTTConfig):
    from .stt import HimaASRSTTService

    return HimaASRSTTService(
        base_url=resolve_realtime_url(),
        model=cfg.model,
        language=resolve_wire_language(cfg.model, cfg.language),
    )
