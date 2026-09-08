"""Pipeline behaviour configuration parsed from agent config."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.runtime.services.pipecat.idle import online_detection_from_behaviour


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

    @property
    def user_idle_timeout(self) -> float:
        if self.online_detection_enabled:
            return self.online_detection_seconds
        return self.user_silence_hangup_seconds


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
    )
