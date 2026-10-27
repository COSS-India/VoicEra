"""Tests for Smallest.ai TTS config validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.providers.cloud.smallest.config import SmallestTTSConfig


def _make(sample_rate: int | str) -> SmallestTTSConfig:
    return SmallestTTSConfig(
        provider="smallest", model="lightning", voice="x", sample_rate=sample_rate, api_key="k"
    )


@pytest.mark.parametrize("rate", [8000, 16000, 24000, 44100])
def test_sample_rate_accepts_every_vendor_supported_rate(rate):
    assert _make(rate).sample_rate == rate


def test_sample_rate_coerces_dropdown_string_to_int():
    # Arrange: the wizard dropdown sends option values as strings.
    # Act
    cfg = _make("24000")

    # Assert
    assert cfg.sample_rate == 24000
    assert isinstance(cfg.sample_rate, int)


@pytest.mark.parametrize("rate", [0, -1, 22050, 48000, "abc"])
def test_sample_rate_rejects_unsupported_value(rate):
    with pytest.raises(ValidationError):
        _make(rate)


def test_sample_rate_error_names_allowed_values():
    with pytest.raises(ValidationError, match="8000, 16000, 24000, 44100"):
        _make(22050)
