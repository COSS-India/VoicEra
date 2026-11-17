"""Silero VAD params and speaking/idle profile switching."""

from __future__ import annotations

from typing import Any

from pipecat.audio.vad.vad_analyzer import VADAnalyzer, VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

DEFAULT_VAD = {
    "confidence": 0.3,
    "start_secs": 0.1,
    "stop_secs": 0.4,
    "min_volume": 0.5,
}


def vad_params_from_behaviour(
    behaviour: dict[str, Any],
    *,
    key: str = "vad",
) -> VADParams:
    """Build VADParams from behaviour[key], falling back to VoicEra defaults."""
    raw = behaviour.get(key) or {}
    return VADParams(
        confidence=float(raw.get("confidence", DEFAULT_VAD["confidence"])),
        start_secs=float(raw.get("start_secs", DEFAULT_VAD["start_secs"])),
        stop_secs=float(raw.get("stop_secs", DEFAULT_VAD["stop_secs"])),
        min_volume=float(raw.get("min_volume", DEFAULT_VAD["min_volume"])),
    )


class VadProfileSwitcher(FrameProcessor):
    """Swap Silero VAD params on bot speaking frames (same signal as MinWords).

    Starts in idle (bot not speaking). Speaking uses ``behaviour.vad``;
    idle uses ``behaviour.vad_idle``.
    """

    def __init__(
        self,
        analyzer: VADAnalyzer,
        *,
        speaking: VADParams,
        idle: VADParams,
    ) -> None:
        super().__init__()
        self._analyzer = analyzer
        self._speaking = speaking
        self._idle = idle
        self._bot_speaking = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStartedSpeakingFrame):
            if not self._bot_speaking:
                self._bot_speaking = True
                self._analyzer.set_params(self._speaking)
        elif isinstance(frame, BotStoppedSpeakingFrame):
            if self._bot_speaking:
                self._bot_speaking = False
                self._analyzer.set_params(self._idle)
        await self.push_frame(frame, direction)
