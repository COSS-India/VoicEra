"""Contract test for the Camb.ai TTS preview adapter."""

from __future__ import annotations

import httpx
import pytest

from apps.providers.cloud.camb.config import CambTTSConfig
from apps.providers.cloud.camb.preview import synthesize
from apps.providers.preview import PreviewProviderError
from apps.providers.tests.preview_harness import json_body, run_adapter, wav_sample_rate

_PCM = httpx.Response(200, content=b"\x00\x01" * 8)


def test_camb_sends_integer_voice_and_wraps_pcm_at_the_models_native_rate():
    # Arrange
    cfg = CambTTSConfig(api_key="test-key", model="mars-pro", language="hi")

    # Act
    audio, request = run_adapter(synthesize, cfg, _PCM, "Namaste")

    # Assert
    assert wav_sample_rate(audio) == 48000
    assert str(request.url) == "https://client.camb.ai/apis/tts-stream"
    assert request.headers["x-api-key"] == "test-key"
    assert json_body(request) == {
        "text": "Namaste",
        "voice_id": 147320,
        "language": "hi-in",
        "speech_model": "mars-pro",
        "output_configuration": {"format": "pcm_s16le"},
    }


def test_camb_sends_user_instructions_only_for_mars_instruct():
    # Act
    _, instruct = run_adapter(synthesize, CambTTSConfig(api_key="k", model="mars-instruct", user_instructions="calm"), _PCM)
    _, flash = run_adapter(synthesize, CambTTSConfig(api_key="k", user_instructions="calm"), _PCM)

    # Assert
    assert json_body(instruct)["user_instructions"] == "calm"
    assert "user_instructions" not in json_body(flash)


@pytest.mark.parametrize(
    "overrides",
    [{"voice": "abc"}, {"voice": "²"}, {"voice": "-5"}, {"voice": "1" * 5000}, {"model": "mars-unknown"}],
)
def test_camb_rejects_non_numeric_voice_or_unknown_model(overrides):
    # Act / Assert
    with pytest.raises(PreviewProviderError):
        run_adapter(synthesize, CambTTSConfig(api_key="k", **overrides), _PCM)
