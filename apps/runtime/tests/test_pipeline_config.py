"""Unit tests for pipeline behaviour configuration parsing."""

from __future__ import annotations

import pytest

from apps.runtime.services.pipecat.config import (
    DEFAULT_VAD_CONFIDENCE,
    DEFAULT_VAD_MIN_VOLUME,
    DEFAULT_VAD_START_SECS,
    DEFAULT_VAD_STOP_SECS,
    pipeline_config_from_behaviour,
)


def test_vad_defaults_when_behaviour_empty() -> None:
    config = pipeline_config_from_behaviour({})
    assert config.vad_stop_secs == DEFAULT_VAD_STOP_SECS
    assert config.vad_min_volume == DEFAULT_VAD_MIN_VOLUME
    assert config.vad_confidence == DEFAULT_VAD_CONFIDENCE
    assert config.vad_start_secs == DEFAULT_VAD_START_SECS


def test_vad_defaults_when_knobs_are_null() -> None:
    config = pipeline_config_from_behaviour(
        {
            "vad_stop_secs": None,
            "vad_min_volume": None,
            "vad_confidence": None,
            "vad_start_secs": None,
        }
    )
    assert config.vad_stop_secs == DEFAULT_VAD_STOP_SECS
    assert config.vad_min_volume == DEFAULT_VAD_MIN_VOLUME
    assert config.vad_confidence == DEFAULT_VAD_CONFIDENCE
    assert config.vad_start_secs == DEFAULT_VAD_START_SECS


def test_vad_overrides_are_applied() -> None:
    config = pipeline_config_from_behaviour(
        {
            "vad_stop_secs": 1.0,
            "vad_min_volume": 0.4,
            "vad_confidence": 0.25,
            "vad_start_secs": 0.2,
        }
    )
    assert config.vad_stop_secs == 1.0
    assert config.vad_min_volume == 0.4
    assert config.vad_confidence == 0.25
    assert config.vad_start_secs == 0.2


@pytest.mark.parametrize(
    "key",
    ["vad_stop_secs", "vad_min_volume", "vad_confidence", "vad_start_secs"],
)
def test_explicit_zero_is_not_replaced_by_default(key: str) -> None:
    config = pipeline_config_from_behaviour({key: 0})
    assert getattr(config, key) == 0.0


def test_vad_knobs_do_not_disturb_existing_behaviour() -> None:
    behaviour = {
        "interruption_min_words": 2,
        "user_silence_hangup_seconds": 30,
        "ignore_user_speech_before_greeting": True,
        "vad_stop_secs": 1.0,
    }
    config = pipeline_config_from_behaviour(behaviour)
    assert config.interruption_min_words == 2
    assert config.user_silence_hangup_seconds == 30
    assert config.ignore_user_speech_before_greeting is True
    assert config.user_idle_timeout == 30
