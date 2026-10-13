"""Contract test for the OpenAI TTS preview adapter."""

from __future__ import annotations

import httpx

from apps.providers.cloud.openai.config import OpenAITTSConfig
from apps.providers.cloud.openai.preview import synthesize
from apps.providers.tests.preview_harness import FAKE_WAV, json_body, run_adapter


def test_openai_sends_wav_request_with_first_rotation_key():
    # Arrange
    cfg = OpenAITTSConfig(api_key=["key-1", "key-2"], voice="coral")

    # Act
    audio, request = run_adapter(synthesize, cfg, httpx.Response(200, content=FAKE_WAV), "Hello")

    # Assert
    assert audio == FAKE_WAV
    assert str(request.url) == "https://api.openai.com/v1/audio/speech"
    assert request.headers["Authorization"] == "Bearer key-1"
    assert json_body(request) == {
        "model": "gpt-4o-mini-tts",
        "voice": "coral",
        "input": "Hello",
        "response_format": "wav",
    }
