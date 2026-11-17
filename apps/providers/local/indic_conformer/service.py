"""Build Pipecat services from Indic Conformer configs."""

from __future__ import annotations

from ...availability import register_local
from ...registry import register_stt
from .catalog import GATEWAY_MODEL_ID, resolve_realtime_url, resolve_wire_language
from .config import IndicConformerSTTConfig

register_local("indic_conformer", GATEWAY_MODEL_ID)


@register_stt
def create_stt(cfg: IndicConformerSTTConfig):
    from .stt import IndicConformerSTTService

    return IndicConformerSTTService(
        base_url=resolve_realtime_url(),
        model=cfg.model,
        language=resolve_wire_language(cfg.model, cfg.language),
    )
