"""Contract test for the Indic Orpheus TTS preview adapter."""

from __future__ import annotations

import httpx
import pytest

from apps.providers.local.indic_orpheus.config import IndicOrpheusTTSConfig
from apps.providers.local.indic_orpheus.preview import synthesize
from apps.providers.preview import PreviewProviderError
from apps.providers.tests.preview_harness import json_body, run_adapter, wav_sample_rate


def test_indic_orpheus_wraps_pcm_at_native_rate_and_sends_style(monkeypatch):
    # Arrange
    monkeypatch.setenv("MODEL_SERVER_URL", "http://model-server:8000/v1/")
    cfg = IndicOrpheusTTSConfig(voice="Kavya", style="happy")

    # Act
    audio, request = run_adapter(synthesize, cfg, httpx.Response(200, content=b"\x00\x01" * 8), "Namaste")

    # Assert
    assert wav_sample_rate(audio) == 24000
    assert str(request.url) == "http://model-server:8000/v1/audio/speech"
    assert json_body(request) == {
        "input": "Namaste",
        "model": "orpheus-indic",
        "voice": "Kavya",
        "response_format": "pcm",
        "instructions": "happy",
    }


def test_indic_orpheus_without_server_url_raises_preview_error(monkeypatch):
    # Arrange
    monkeypatch.delenv("MODEL_SERVER_URL", raising=False)

    # Act / Assert
    with pytest.raises(PreviewProviderError, match="MODEL_SERVER_URL"):
        run_adapter(synthesize, IndicOrpheusTTSConfig(), httpx.Response(200, content=b"\x00"))
