"""Build Pipecat services from Indic Nemotron configs."""

from __future__ import annotations

from ...availability import register_local
from ...registry import register_stt
from .catalog import GATEWAY_MODEL_ID, resolve_wire_language, resolve_ws_url
from .config import IndicNemotronSTTConfig

register_local("indic_nemotron", GATEWAY_MODEL_ID)


@register_stt
def create_stt(cfg: IndicNemotronSTTConfig):
    from .stt import IndicNemotronSTTService

    return IndicNemotronSTTService(
        ws_url=resolve_ws_url(),
        language=resolve_wire_language(cfg.model, cfg.language),
    )
