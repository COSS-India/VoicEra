"""Contract test for the Deepgram TTS preview adapter."""

from __future__ import annotations

import httpx

from apps.providers.cloud.deepgram.config import DeepgramTTSConfig
from apps.providers.cloud.deepgram.preview import synthesize
from apps.providers.tests.preview_harness import json_body, run_adapter, wav_sample_rate


def test_deepgram_requests_raw_linear16_with_voice_as_model():
    # Arrange
    cfg = DeepgramTTSConfig(api_key=["key-1", "key-2"], voice="aura-2-thalia-en")

    # Act
    audio, request = run_adapter(synthesize, cfg, httpx.Response(200, content=b"\x00\x01" * 8), "Hello")

    # Assert
    assert wav_sample_rate(audio) == 16000
    assert request.url.path == "/v1/speak"
    assert dict(request.url.params) == {
        "model": "aura-2-thalia-en",
        "encoding": "linear16",
        "sample_rate": "16000",
        "container": "none",
    }
    assert request.headers["Authorization"] == "Token key-1"
    assert json_body(request) == {"text": "Hello"}
