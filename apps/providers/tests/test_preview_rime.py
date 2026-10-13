"""Contract test for the Rime TTS preview adapter."""

from __future__ import annotations

import httpx

from apps.providers.cloud.rime.config import RimeTTSConfig
from apps.providers.cloud.rime.preview import synthesize
from apps.providers.tests.preview_harness import json_body, run_adapter, wav_sample_rate


def test_rime_sends_iso639_3_language_and_speed_unchanged_as_speed_alpha():
    # Arrange
    cfg = RimeTTSConfig(api_key="test-key", voice="celeste", language="hi", speed=1.5)

    # Act
    audio, request = run_adapter(synthesize, cfg, httpx.Response(200, content=b"\x00\x01" * 8), "Namaste")

    # Assert
    assert wav_sample_rate(audio) == 16000
    assert str(request.url) == "https://users.rime.ai/v1/rime-tts"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert request.headers["Accept"] == "audio/pcm"
    assert json_body(request) == {
        "text": "Namaste",
        "speaker": "celeste",
        "modelId": "arcana",
        "samplingRate": 16000,
        "lang": "hin",
        "speedAlpha": 1.5,
    }
