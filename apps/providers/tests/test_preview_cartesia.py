"""Contract test for the Cartesia TTS preview adapter."""

from __future__ import annotations

import httpx

from apps.providers.cloud.cartesia.config import CartesiaTTSConfig
from apps.providers.cloud.cartesia.preview import synthesize
from apps.providers.tests.preview_harness import FAKE_WAV, json_body, run_adapter


def test_cartesia_requests_16k_wav_with_version_header_and_generation_config():
    # Arrange
    cfg = CartesiaTTSConfig(api_key="test-key", voice="voice-uuid", language="hi", speed=1.2, volume=0.8)

    # Act
    audio, request = run_adapter(synthesize, cfg, httpx.Response(200, content=FAKE_WAV), "Namaste")

    # Assert
    assert audio == FAKE_WAV
    assert str(request.url) == "https://api.cartesia.ai/tts/bytes"
    assert request.headers["X-API-Key"] == "test-key"
    assert request.headers["Cartesia-Version"] == "2026-03-01"
    assert json_body(request) == {
        "model_id": "sonic-3.5",
        "transcript": "Namaste",
        "voice": {"mode": "id", "id": "voice-uuid"},
        "language": "hi",
        "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 16000},
        "generation_config": {"speed": 1.2, "volume": 0.8},
    }
