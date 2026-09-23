"""Silero VAD params parsed from agent behaviour config."""

from __future__ import annotations

from typing import Any

from pipecat.audio.vad.vad_analyzer import VADParams

DEFAULT_VAD = {
    "confidence": 0.3,
    "start_secs": 0.1,
    "stop_secs": 0.4,
    "min_volume": 0.5,
}


def vad_params_from_behaviour(behaviour: dict[str, Any]) -> VADParams:
    """Build VADParams from behaviour.vad, falling back to VoicEra defaults."""
    raw = behaviour.get("vad") or {}
    return VADParams(
        confidence=float(raw.get("confidence", DEFAULT_VAD["confidence"])),
        start_secs=float(raw.get("start_secs", DEFAULT_VAD["start_secs"])),
        stop_secs=float(raw.get("stop_secs", DEFAULT_VAD["stop_secs"])),
        min_volume=float(raw.get("min_volume", DEFAULT_VAD["min_volume"])),
    )
