"""Resolve language-judge settings from env + agent behaviour."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

DEFAULT_MIN_WORDS = 3
DEFAULT_MIN_SCORE = 0.8
DEFAULT_MARGIN = 0.3
DEFAULT_COOLDOWN_SEC = 3.0
DEFAULT_NEMOTRON_TIMEOUT_S = 3.0
DEFAULT_INDICLID_TIMEOUT_S = 1.5
# The gate waits this much longer than the Nemotron call before giving up.
_HOLD_SLACK_S = 0.5

LANGUAGE_SWITCHING_MODE_LID = "lid"
LANGUAGE_SWITCHING_MODE_DETERMINISTIC = "deterministic"


@dataclass(frozen=True)
class LidConfig:
    """Runtime settings for the Nemotron + IndicLID language judge."""

    nemotron_url: str
    indiclid_url: str
    min_words: int = DEFAULT_MIN_WORDS
    min_score: float = DEFAULT_MIN_SCORE
    margin: float = DEFAULT_MARGIN
    cooldown_sec: float = DEFAULT_COOLDOWN_SEC
    # Language being left -> message spoken by that language's own TTS the moment
    # a switch away from it is decided. Languages without an entry stay silent.
    handoff_messages: dict[str, str] = field(default_factory=dict)
    nemotron_timeout_s: float = DEFAULT_NEMOTRON_TIMEOUT_S
    indiclid_timeout_s: float = DEFAULT_INDICLID_TIMEOUT_S

    @property
    def hold_deadline_s(self) -> float:
        """Longest the gate holds the main ASR text waiting for Nemotron."""
        return self.nemotron_timeout_s + _HOLD_SLACK_S


def _handoff_messages(raw: Any) -> dict[str, str]:
    """``{"hi": " Ek minute "}`` -> ``{"hi": "Ek minute"}``; drops blanks and bad entries."""
    if not isinstance(raw, dict):
        return {}
    messages: dict[str, str] = {}
    for language, message in raw.items():
        key = str(language or "").strip().lower().split("-")[0]
        text = str(message or "").strip()
        if key and text:
            messages[key] = text
    return messages


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


def _positive_float(value: Any, default: float) -> float:
    parsed = _as_float(value, default)
    return parsed if parsed > 0 else default


def resolve_lid_config(
    behaviour: dict[str, Any] | None,
    *,
    multilingual: bool,
) -> LidConfig | None:
    """Return LID config when the judge should run; otherwise None.

    Requires a multilingual agent, ``language_switching_mode == "lid"``, and
    both ``NEMOTRON_LID_URL`` and ``INDICLID_URL``. A missing URL logs a warning
    and stays off (fail closed — does not fall back to the LLM tool).
    """
    if not multilingual:
        return None
    if language_switching_mode(behaviour) != LANGUAGE_SWITCHING_MODE_LID:
        return None

    urls = {
        name: (os.getenv(name) or "").strip().rstrip("/")
        for name in ("NEMOTRON_LID_URL", "INDICLID_URL")
    }
    missing = [name for name, url in urls.items() if not url]
    if missing:
        logger.warning(
            "language_switching_mode=lid but {} unset — language judge disabled "
            "(no fallback to switch_language tool)",
            ", ".join(missing),
        )
        return None

    raw = (behaviour or {}).get("lid") or {}
    if not isinstance(raw, dict):
        raw = {}

    return LidConfig(
        nemotron_url=urls["NEMOTRON_LID_URL"],
        indiclid_url=urls["INDICLID_URL"],
        min_words=int(_positive_float(raw.get("min_words"), DEFAULT_MIN_WORDS)),
        min_score=_as_float(raw.get("min_score"), DEFAULT_MIN_SCORE),
        margin=_as_float(raw.get("margin"), DEFAULT_MARGIN),
        cooldown_sec=_as_float(raw.get("cooldown_sec"), DEFAULT_COOLDOWN_SEC),
        handoff_messages=_handoff_messages(raw.get("handoff_messages")),
        nemotron_timeout_s=_positive_float(
            os.getenv("NEMOTRON_LID_TIMEOUT_S"), DEFAULT_NEMOTRON_TIMEOUT_S
        ),
        indiclid_timeout_s=_positive_float(
            os.getenv("INDICLID_TIMEOUT_S"), DEFAULT_INDICLID_TIMEOUT_S
        ),
    )
