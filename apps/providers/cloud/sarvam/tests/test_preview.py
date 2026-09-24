"""Contract test for the Sarvam TTS preview adapter."""

from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

from apps.providers.cloud.sarvam.config import SarvamTTSConfig
from apps.providers.cloud.sarvam.preview import synthesize
from apps.providers.preview import PreviewProviderError


def _config(**overrides) -> SarvamTTSConfig:
    defaults = dict(api_key="test-key", voice="shubh", language="hi", model="bulbul:v3", speed=1.0)
    defaults.update(overrides)
    return SarvamTTSConfig(**defaults)


def test_synthesize_sends_expected_payload_and_headers():
    # Arrange
    captured: dict = {}
    fake_wav = b"RIFF....WAVEfmt "

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"audios": [base64.b64encode(fake_wav).decode()]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    # Act
    result = asyncio.run(synthesize(_config(speed=1.5), "Namaste", client))
    asyncio.run(client.aclose())

    # Assert
    assert result == fake_wav
    assert captured["url"] == "https://api.sarvam.ai/text-to-speech"
    assert captured["headers"]["api-subscription-key"] == "test-key"
    body = captured["body"]
    assert body["text"] == "Namaste"
    assert body["target_language_code"] == "hi-IN"  # canonical "hi" -> vendor "hi-IN"
    assert body["speaker"] == "shubh"
    assert body["pace"] == 1.5  # speed -> pace, same conversion as the live-call service
    assert body["speech_sample_rate"] == 16000
    assert body["output_audio_codec"] == "wav"


def test_synthesize_raises_preview_error_on_http_error():
    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    # Act / Assert
    with pytest.raises(PreviewProviderError, match="401"):
        asyncio.run(synthesize(_config(), "hi", client))
    asyncio.run(client.aclose())


def test_synthesize_raises_preview_error_on_empty_audio():
    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"audios": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    # Act / Assert
    with pytest.raises(PreviewProviderError, match="no audio"):
        asyncio.run(synthesize(_config(), "hi", client))
    asyncio.run(client.aclose())
