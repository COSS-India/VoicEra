"""Contract test for the Smallest.ai TTS preview adapter."""

from __future__ import annotations

import httpx

from apps.providers.cloud.smallest.config import SmallestTTSConfig
from apps.providers.cloud.smallest.preview import synthesize
from apps.providers.tests.preview_harness import json_body, run_adapter, wav_sample_rate


def test_smallest_uses_the_users_sample_rate_for_request_and_wav_header():
    # Arrange
    cfg = SmallestTTSConfig(
        api_key="test-key", voice="meher", model="lightning_v3.1_pro", language="hi", speed=1.3, sample_rate=44100
    )

    # Act
    audio, request = run_adapter(synthesize, cfg, httpx.Response(200, content=b"\x00\x01" * 8), "Namaste")

    # Assert
    assert wav_sample_rate(audio) == 44100
    assert str(request.url) == "https://api.smallest.ai/waves/v1/tts"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert json_body(request) == {
        "text": "Namaste",
        "voice_id": "meher",
        "model": "lightning_v3.1_pro",
        "language": "hi",
        "sample_rate": 44100,
        "speed": 1.3,
        "output_format": "pcm",
    }
