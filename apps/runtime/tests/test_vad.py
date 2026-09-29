"""Unit tests for Silero VAD params from agent behaviour."""

from __future__ import annotations

from apps.runtime.services.pipecat.vad import DEFAULT_VAD, vad_params_from_behaviour


def test_vad_params_missing_uses_defaults() -> None:
    params = vad_params_from_behaviour({})
    assert params.confidence == DEFAULT_VAD["confidence"]
    assert params.start_secs == DEFAULT_VAD["start_secs"]
    assert params.stop_secs == DEFAULT_VAD["stop_secs"]
    assert params.min_volume == DEFAULT_VAD["min_volume"]


def test_vad_params_empty_vad_uses_defaults() -> None:
    params = vad_params_from_behaviour({"vad": {}})
    assert params.confidence == DEFAULT_VAD["confidence"]
    assert params.start_secs == DEFAULT_VAD["start_secs"]
    assert params.stop_secs == DEFAULT_VAD["stop_secs"]
    assert params.min_volume == DEFAULT_VAD["min_volume"]


def test_vad_params_partial_override() -> None:
    params = vad_params_from_behaviour({"vad": {"confidence": 0.7, "stop_secs": 0.8}})
    assert params.confidence == 0.7
    assert params.stop_secs == 0.8
    assert params.start_secs == DEFAULT_VAD["start_secs"]
    assert params.min_volume == DEFAULT_VAD["min_volume"]


def test_vad_params_full_override() -> None:
    params = vad_params_from_behaviour(
        {
            "vad": {
                "confidence": 0.6,
                "start_secs": 0.2,
                "stop_secs": 0.5,
                "min_volume": 0.4,
            }
        }
    )
    assert params.confidence == 0.6
    assert params.start_secs == 0.2
    assert params.stop_secs == 0.5
    assert params.min_volume == 0.4
