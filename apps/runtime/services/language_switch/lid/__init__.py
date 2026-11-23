"""Nemotron ASR + IndicLID judge for automatic language switching."""

from apps.runtime.services.language_switch.lid.client import NemotronLidClient
from apps.runtime.services.language_switch.lid.config import (
    LANGUAGE_SWITCHING_MODE_DETERMINISTIC,
    LANGUAGE_SWITCHING_MODE_LID,
    LidConfig,
    language_switching_mode,
    resolve_lid_config,
)
from apps.runtime.services.language_switch.lid.indiclid import IndicLidClient
from apps.runtime.services.language_switch.lid.judge import JudgeDecision, LanguageJudge
from apps.runtime.services.language_switch.lid.processor import LidTapProcessor

__all__ = [
    "LANGUAGE_SWITCHING_MODE_DETERMINISTIC",
    "LANGUAGE_SWITCHING_MODE_LID",
    "IndicLidClient",
    "JudgeDecision",
    "LanguageJudge",
    "LidConfig",
    "LidTapProcessor",
    "NemotronLidClient",
    "language_switching_mode",
    "resolve_lid_config",
]
