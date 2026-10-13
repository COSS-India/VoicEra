"""Contract test for the xAI TTS preview adapter."""

from __future__ import annotations

import httpx
import pytest

from apps.providers.cloud.xai.config import XAITTSConfig
from apps.providers.cloud.xai.preview import synthesize
from apps.providers.tests.preview_harness import json_body, run_adapter, wav_sample_rate


@pytest.mark.parametrize(("language", "wire"), [("hi", "hi"), ("multi", "auto")])
def test_xai_requests_16k_pcm_with_vendor_language(language, wire):
    # Arrange
    cfg = XAITTSConfig(api_key="test-key", voice="eve", language=language)

    # Act
    audio, request = run_adapter(synthesize, cfg, httpx.Response(200, content=b"\x00\x01" * 8), "Hello")

    # Assert
    assert wav_sample_rate(audio) == 16000
    assert str(request.url) == "https://api.x.ai/v1/tts"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert json_body(request) == {
        "text": "Hello",
        "voice_id": "eve",
        "output_format": {"codec": "pcm", "sample_rate": 16000},
        "language": wire,
    }
