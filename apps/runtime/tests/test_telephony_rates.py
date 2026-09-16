"""Tests for VI telephony sample rate resolution."""

from __future__ import annotations

from types import SimpleNamespace

from apps.runtime.services.pipecat.telephony_rates import (
    tts_native_sample_rate,
    vi_pipeline_sample_rate,
)


def test_tts_native_sample_rate_prefers_init_rate() -> None:
    tts = SimpleNamespace(_init_sample_rate=24000, sample_rate=8000)
    assert tts_native_sample_rate(tts, fallback=8000) == 24000


def test_vi_pipeline_rate_stays_at_wire_for_8k_tts() -> None:
    tts = SimpleNamespace(_init_sample_rate=8000, sample_rate=8000)
    assert vi_pipeline_sample_rate(tts, wire_rate=8000) == 8000


def test_vi_pipeline_rate_uses_16k_for_16k_tts() -> None:
    tts = SimpleNamespace(_init_sample_rate=16000, sample_rate=16000)
    assert vi_pipeline_sample_rate(tts, wire_rate=8000) == 16000


def test_vi_pipeline_rate_caps_orpheus_24k_at_16k_for_silero() -> None:
    tts = SimpleNamespace(_init_sample_rate=24000, sample_rate=24000)
    assert vi_pipeline_sample_rate(tts, wire_rate=8000) == 16000
