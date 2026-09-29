"""Tests for Smallest.ai TTS config validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from .config import SmallestTTSConfig


def test_sample_rate_accepts_catalog_value():
    cfg = SmallestTTSConfig(
        provider="smallest", model="lightning", voice="x", sample_rate=24000, api_key="k"
    )
    assert cfg.sample_rate == 24000


def test_sample_rate_rejects_zero():
    with pytest.raises(ValidationError):
        SmallestTTSConfig(
            provider="smallest", model="lightning", voice="x", sample_rate=0, api_key="k"
        )


def test_sample_rate_rejects_value_outside_catalog():
    with pytest.raises(ValidationError):
        SmallestTTSConfig(
            provider="smallest", model="lightning", voice="x", sample_rate=44100, api_key="k"
        )
