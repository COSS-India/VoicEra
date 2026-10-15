"""Contract test for the Azure Speech TTS preview adapter."""

from __future__ import annotations

import httpx
import pytest

from apps.providers.cloud.azure_speech.config import AzureSpeechTTSConfig
from apps.providers.cloud.azure_speech.preview import synthesize
from apps.providers.preview import PreviewProviderError
from apps.providers.tests.preview_harness import FAKE_WAV, run_adapter


def test_azure_posts_escaped_ssml_to_the_regions_endpoint():
    # Arrange
    cfg = AzureSpeechTTSConfig(api_key="test-key", region="centralindia", language="hi", voice="hi-IN-SwaraNeural", speed=1.5)

    # Act
    audio, request = run_adapter(synthesize, cfg, httpx.Response(200, content=FAKE_WAV), "Tom & <Jerry>")

    # Assert
    assert audio == FAKE_WAV
    assert str(request.url) == "https://centralindia.tts.speech.microsoft.com/cognitiveservices/v1"
    assert request.headers["Ocp-Apim-Subscription-Key"] == "test-key"
    assert request.headers["X-Microsoft-OutputFormat"] == "riff-16khz-16bit-mono-pcm"
    assert request.headers["Content-Type"] == "application/ssml+xml"
    assert request.headers["User-Agent"]
    assert request.content.decode() == (
        "<speak version='1.0' xml:lang='hi-IN' xmlns='http://www.w3.org/2001/10/synthesis'>"
        "<voice name='hi-IN-SwaraNeural'><prosody rate='1.5'>Tom &amp; &lt;Jerry&gt;</prosody></voice></speak>"
    )


def test_azure_escapes_quotes_in_the_voice_attribute():
    # Act
    _, request = run_adapter(
        synthesize, AzureSpeechTTSConfig(api_key="k", voice="x' y='z"), httpx.Response(200, content=FAKE_WAV)
    )

    # Assert
    assert "<voice name='x&apos; y=&apos;z'>" in request.content.decode()


def test_azure_accepts_a_region_in_any_case():
    # Act
    _, request = run_adapter(
        synthesize, AzureSpeechTTSConfig(api_key="k", region=" EastUS "), httpx.Response(200, content=FAKE_WAV)
    )

    # Assert
    assert request.url.host == "eastus.tts.speech.microsoft.com"


@pytest.mark.parametrize("region", ["evil.example.com/#", "eastus.attacker.net", ""])
def test_azure_rejects_regions_outside_the_allowlist(region):
    # Act / Assert
    with pytest.raises(PreviewProviderError, match="region"):
        run_adapter(synthesize, AzureSpeechTTSConfig(api_key="k", region=region), httpx.Response(200, content=FAKE_WAV))
