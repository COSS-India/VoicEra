"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_stt
from .config import SpeechmaticsSTTConfig


@register_stt
def create_stt(cfg: SpeechmaticsSTTConfig):
    from pipecat.services.speechmatics.stt import (
        SpeechmaticsSTTService,
        SpeechmaticsSTTSettings,
    )
    from speechmatics.voice import OperatingPoint

    try:
        operating_point = OperatingPoint(cfg.model)
    except ValueError:
        operating_point = OperatingPoint[cfg.model.upper()]

    return SpeechmaticsSTTService(
        api_key=cfg.api_key,
        settings=SpeechmaticsSTTSettings(
            language=cfg.language,
            operating_point=operating_point,
        ),
    )
