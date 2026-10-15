"""Contract test for the ElevenLabs TTS preview adapter."""

from __future__ import annotations

import httpx
import pytest

from apps.providers.cloud.elevenlabs.config import ElevenLabsTTSConfig
from apps.providers.cloud.elevenlabs.preview import synthesize
from apps.providers.preview import PreviewProviderError
from apps.providers.tests.preview_harness import json_body, run_adapter, wav_sample_rate

_PCM = httpx.Response(200, content=b"\x00\x01" * 8)


def _config(**overrides: object) -> ElevenLabsTTSConfig:
    return ElevenLabsTTSConfig(**{"api_key": "test-key", "voice": "abc123", "language": "hi", **overrides})


def test_elevenlabs_requests_16k_pcm_and_maps_speed_and_language():
    # Act
    audio, request = run_adapter(synthesize, _config(speed=1.1), _PCM, "Namaste")

    # Assert
    assert wav_sample_rate(audio) == 16000
    assert str(request.url) == "https://api.elevenlabs.io/v1/text-to-speech/abc123?output_format=pcm_16000"
    assert request.headers["xi-api-key"] == "test-key"
    assert json_body(request) == {
        "text": "Namaste",
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {"speed": 1.1},
        "language_code": "hi",
    }


def test_elevenlabs_omits_language_code_for_models_that_reject_it():
    # Act
    _, request = run_adapter(synthesize, _config(model="eleven_multilingual_v2"), _PCM)

    # Assert
    assert "language_code" not in json_body(request)


@pytest.mark.parametrize("voice", ["../v1/user", "abc/def", "abc?x=1"])
def test_elevenlabs_rejects_voice_ids_that_would_change_the_url_path(voice):
    # Act / Assert
    with pytest.raises(PreviewProviderError, match="alphanumeric"):
        run_adapter(synthesize, _config(voice=voice), _PCM)
