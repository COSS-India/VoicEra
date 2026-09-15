"""Pipeline behaviour configuration parsed from agent config."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.runtime.services.pipecat.idle import online_detection_from_behaviour

# Silero VAD defaults tuned for telephony audio — more sensitive and more
# patient than Pipecat's own defaults, which clip callers mid-utterance.
DEFAULT_VAD_STOP_SECS = 0.4
DEFAULT_VAD_MIN_VOLUME = 0.5
DEFAULT_VAD_CONFIDENCE = 0.3
DEFAULT_VAD_START_SECS = 0.1


@dataclass(frozen=True)
class PipelineConfig:
    ignore_user_speech_before_greeting: bool
    interruption_min_words: int
    online_detection_enabled: bool
    online_detection_seconds: float
    online_detection_repeats: int
    online_detection_message: str
    online_detection_closing_message: str
    user_silence_hangup_seconds: float
    vad_stop_secs: float
    vad_min_volume: float
    vad_confidence: float
    vad_start_secs: float

    @property
    def user_idle_timeout(self) -> float:
        if self.online_detection_enabled:
            return self.online_detection_seconds
        return self.user_silence_hangup_seconds


def _behaviour_float(behaviour: dict[str, Any], key: str, default: float) -> float:
    """Read a float knob, falling back to ``default`` when unset or null.

    Unlike ``behaviour.get(key) or default`` this keeps an explicit ``0`` —
    zero is meaningful for the VAD knobs (e.g. ``vad_min_volume``).
    """
    value = behaviour.get(key)
    return default if value is None else float(value)


def pipeline_config_from_behaviour(behaviour: dict[str, Any]) -> PipelineConfig:
    (
        online_detection_enabled,
        online_detection_seconds,
        online_detection_repeats,
        online_detection_message,
        online_detection_closing_message,
        user_silence_hangup_seconds,
    ) = online_detection_from_behaviour(behaviour)
    return PipelineConfig(
        ignore_user_speech_before_greeting=bool(
            behaviour.get("ignore_user_speech_before_greeting", False)
        ),
        interruption_min_words=int(behaviour.get("interruption_min_words") or 0),
        online_detection_enabled=online_detection_enabled,
        online_detection_seconds=online_detection_seconds,
        online_detection_repeats=online_detection_repeats,
        online_detection_message=online_detection_message,
        online_detection_closing_message=online_detection_closing_message,
        user_silence_hangup_seconds=user_silence_hangup_seconds,
        vad_stop_secs=_behaviour_float(
            behaviour, "vad_stop_secs", DEFAULT_VAD_STOP_SECS
        ),
        vad_min_volume=_behaviour_float(
            behaviour, "vad_min_volume", DEFAULT_VAD_MIN_VOLUME
        ),
        vad_confidence=_behaviour_float(
            behaviour, "vad_confidence", DEFAULT_VAD_CONFIDENCE
        ),
        vad_start_secs=_behaviour_float(
            behaviour, "vad_start_secs", DEFAULT_VAD_START_SECS
        ),
    )
