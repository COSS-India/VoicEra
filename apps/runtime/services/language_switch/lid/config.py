"""Resolve LID tap settings from env + agent behaviour."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from loguru import logger

# Nemotron linear probe languages (no English).
PROBE_LANGUAGE_CODES = frozenset({"bn", "gu", "hi", "kn", "ml", "mr", "pa", "ta", "te"})

DEFAULT_MIN_CONFIDENCE = 0.7
DEFAULT_MIN_AUDIO_SEC = 1.8
DEFAULT_COOLDOWN_SEC = 3.0
DEFAULT_TIMEOUT_S = 2.0

LANGUAGE_SWITCHING_MODE_LID = "lid"
LANGUAGE_SWITCHING_MODE_DETERMINISTIC = "deterministic"


@dataclass(frozen=True)
class LidConfig:
    """Runtime settings for the parallel LID tap."""

    url: str
    min_confidence: float = DEFAULT_MIN_CONFIDENCE
    min_audio_sec: float = DEFAULT_MIN_AUDIO_SEC
    cooldown_sec: float = DEFAULT_COOLDOWN_SEC
    timeout_s: float = DEFAULT_TIMEOUT_S


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def language_switching_mode(behaviour: dict[str, Any] | None) -> str:
    """Return normalized switching mode (default deterministic)."""
    raw = (behaviour or {}).get("language_switching_mode") or LANGUAGE_SWITCHING_MODE_DETERMINISTIC
    mode = str(raw).strip().lower()
    if mode == LANGUAGE_SWITCHING_MODE_LID:
        return LANGUAGE_SWITCHING_MODE_LID
    return LANGUAGE_SWITCHING_MODE_DETERMINISTIC


def resolve_lid_config(
    behaviour: dict[str, Any] | None,
    *,
    multilingual: bool,
) -> LidConfig | None:
    """Return LID config when the tap should run; otherwise None.

    Requires multilingual agent, ``language_switching_mode == \"lid\"``, and
    ``NEMOTRON_LID_URL``. Missing URL in LID mode logs a warning and stays off
    (fail closed — does not fall back to the LLM tool).
    """
    if not multilingual:
        return None

    mode = language_switching_mode(behaviour)
    if mode != LANGUAGE_SWITCHING_MODE_LID:
        return None

    url = (os.getenv("NEMOTRON_LID_URL") or "").strip().rstrip("/")
    if not url:
        logger.warning(
            "language_switching_mode=lid but NEMOTRON_LID_URL is unset — "
            "LID tap disabled (no fallback to switch_language tool)"
        )
        return None

    raw = (behaviour or {}).get("lid") or {}
    if not isinstance(raw, dict):
        raw = {}

    timeout_s = _as_float(
        os.getenv("NEMOTRON_LID_TIMEOUT_S"),
        DEFAULT_TIMEOUT_S,
    )
    if timeout_s <= 0:
        timeout_s = DEFAULT_TIMEOUT_S

    return LidConfig(
        url=url,
        min_confidence=_as_float(raw.get("min_confidence"), DEFAULT_MIN_CONFIDENCE),
        min_audio_sec=_as_float(raw.get("min_audio_sec"), DEFAULT_MIN_AUDIO_SEC),
        cooldown_sec=_as_float(raw.get("cooldown_sec"), DEFAULT_COOLDOWN_SEC),
        timeout_s=timeout_s,
    )
