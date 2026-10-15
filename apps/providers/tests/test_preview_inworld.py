"""Contract test for the Inworld TTS preview adapter."""

from __future__ import annotations

import base64

import httpx
import pytest

from apps.providers.cloud.inworld.config import InworldTTSConfig
from apps.providers.cloud.inworld.preview import synthesize
from apps.providers.preview import PreviewProviderError
from apps.providers.tests.preview_harness import json_body, run_adapter, wav_sample_rate

_CFG = InworldTTSConfig(api_key="basic-cred", voice="Ashley", speed=1.25, delivery_mode="STABLE")


def test_inworld_requests_16k_pcm_and_decodes_base64_audio():
    # Arrange
    response = httpx.Response(200, json={"audioContent": base64.b64encode(b"\x00\x01" * 8).decode()})

    # Act
    audio, request = run_adapter(synthesize, _CFG, response, "Hello")

    # Assert
    assert wav_sample_rate(audio) == 16000
    assert str(request.url) == "https://api.inworld.ai/tts/v1/voice"
    assert request.headers["Authorization"] == "Basic basic-cred"
    assert json_body(request) == {
        "text": "Hello",
        "voiceId": "Ashley",
        "modelId": "inworld-tts-2",
        "audioConfig": {"audioEncoding": "PCM", "sampleRateHertz": 16000, "speakingRate": 1.25},
        "deliveryMode": "STABLE",
        "language": "en-US",
    }


def test_inworld_strips_a_wav_header_returned_for_pcm():
    # Arrange
    header = b"RIFF" + b"\x00" * 40
    response = httpx.Response(200, json={"audioContent": base64.b64encode(header + b"\x01\x02").decode()})

    # Act
    audio, _ = run_adapter(synthesize, _CFG, response)

    # Assert: exactly one header, and the samples are only the PCM after it.
    assert audio.count(b"RIFF") == 1
    assert audio.endswith(b"\x01\x02")
    assert len(audio) == 44 + 2


@pytest.mark.parametrize(
    "body",
    [
        {"audioContent": ""},
        {"audioContent": "!!not-base64"},
        {"audioContent": base64.b64encode(b"RIFF" + b"\x00" * 40).decode()},  # header only, no frames
        {"no": "audio"},
        ["not", "a", "dict"],
    ],
)
def test_inworld_raises_preview_error_on_empty_or_malformed_200(body):
    # Act / Assert
    with pytest.raises(PreviewProviderError):
        run_adapter(synthesize, _CFG, httpx.Response(200, json=body))
