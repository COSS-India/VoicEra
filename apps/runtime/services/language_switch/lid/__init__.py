"""Parallel Nemotron LID tap for automatic language switching."""

from apps.runtime.services.language_switch.lid.client import NemotronLidClient
from apps.runtime.services.language_switch.lid.config import (
    LANGUAGE_SWITCHING_MODE_DETERMINISTIC,
    LANGUAGE_SWITCHING_MODE_LID,
    LidConfig,
    language_switching_mode,
    resolve_lid_config,
)
from apps.runtime.services.language_switch.lid.policy import LidPolicy
from apps.runtime.services.language_switch.lid.processor import LidTapProcessor
from apps.runtime.services.language_switch.lid.types import LidDecision, LidResult

__all__ = [
    "LANGUAGE_SWITCHING_MODE_DETERMINISTIC",
    "LANGUAGE_SWITCHING_MODE_LID",
    "LidConfig",
    "LidDecision",
    "LidPolicy",
    "LidResult",
    "LidTapProcessor",
    "NemotronLidClient",
    "language_switching_mode",
    "resolve_lid_config",
]
