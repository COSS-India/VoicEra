"""Tests for telephony pipeline sample-rate resolution."""

from __future__ import annotations

from types import SimpleNamespace

from apps.telephony.providers.vi.rates import (
    pipeline_sample_rate,
    tts_native_sample_rate,
)
from apps.telephony.rates import resolve_pipeline_rates
from apps.telephony.registry import load_providers


def test_tts_native_sample_rate_prefers_init_rate() -> None:
    tts = SimpleNamespace(_init_sample_rate=24000, sample_rate=8000)
    assert tts_native_sample_rate(tts, fallback=8000) == 24000


def test_vi_pipeline_rate_stays_at_wire_for_8k_tts() -> None:
    tts = SimpleNamespace(_init_sample_rate=8000, sample_rate=8000)
    assert pipeline_sample_rate(tts, wire_rate=8000) == 8000


def test_vi_pipeline_rate_uses_16k_for_16k_tts() -> None:
    tts = SimpleNamespace(_init_sample_rate=16000, sample_rate=16000)
    assert pipeline_sample_rate(tts, wire_rate=8000) == 16000


def test_vi_pipeline_rate_caps_orpheus_24k_at_16k_for_silero() -> None:
    tts = SimpleNamespace(_init_sample_rate=24000, sample_rate=24000)
    assert pipeline_sample_rate(tts, wire_rate=8000) == 16000


def test_tts_native_sample_rate_reads_switcher_services() -> None:
    inner = SimpleNamespace(_init_sample_rate=24000, sample_rate=24000)
    switcher = SimpleNamespace(services=[inner], sample_rate=0)
    assert tts_native_sample_rate(switcher, fallback=8000) == 24000


def test_resolve_pipeline_rates_vi_registered() -> None:
    load_providers()
    tts = SimpleNamespace(_init_sample_rate=24000, sample_rate=24000)
    rates = resolve_pipeline_rates("vi", tts)
    assert rates is not None
    assert rates.wire_rate == 8000
    assert rates.pipeline_rate == 16000
    assert rates.recording_rate == 24000


def test_resolve_pipeline_rates_unknown_provider() -> None:
    load_providers()
    assert resolve_pipeline_rates("plivo", SimpleNamespace()) is None
