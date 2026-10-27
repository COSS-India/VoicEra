"""Contract test for the Google Cloud TTS preview adapter."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from apps.providers.cloud.google import preview
from apps.providers.cloud.google.config import GoogleTTSConfig
from apps.providers.cloud.google.preview import synthesize
from apps.providers.preview import PreviewProviderError
from apps.providers.tests.preview_harness import FAKE_WAV, json_body, run_adapter

_SA_JSON = json.dumps(
    {"type": "service_account", "client_email": "x@y.iam", "token_uri": "http://169.254.169.254/latest"}
)
_AUDIO = httpx.Response(200, json={"audioContent": base64.b64encode(FAKE_WAV).decode()})


class _FakeCredentials:
    def __init__(self) -> None:
        self.valid = False
        self.token = None
        self.refreshes = 0
        self.request = None

    def refresh(self, request) -> None:
        self.refreshes += 1
        self.request = request
        self.valid, self.token = True, "minted-token"


@pytest.fixture
def minted(monkeypatch) -> list[_FakeCredentials]:
    """Replace service-account loading with a fake and record each credentials object made."""
    made: list[_FakeCredentials] = []

    def from_info(info, scopes):
        assert info["client_email"] == "x@y.iam"
        assert info["token_uri"] == "https://oauth2.googleapis.com/token"  # never the JSON's own URL
        assert scopes == ("https://www.googleapis.com/auth/cloud-platform",)
        made.append(_FakeCredentials())
        return made[-1]

    monkeypatch.setattr(preview, "_CREDENTIALS", {})
    monkeypatch.setattr(preview.service_account.Credentials, "from_service_account_info", from_info)
    return made


def test_google_sends_linear16_request_with_minted_bearer_token(minted):
    # Arrange
    cfg = GoogleTTSConfig(credentials=_SA_JSON, language="hi", voice="hi-IN-Chirp3-HD-Kore", speed=1.2)

    # Act
    audio, request = run_adapter(synthesize, cfg, _AUDIO, "Namaste")

    # Assert
    assert audio == FAKE_WAV
    assert str(request.url) == "https://texttospeech.googleapis.com/v1/text:synthesize"
    assert request.headers["Authorization"] == "Bearer minted-token"
    assert json_body(request) == {
        "input": {"text": "Namaste"},
        "voice": {"languageCode": "hi-IN", "name": "hi-IN-Chirp3-HD-Kore"},
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 16000, "speakingRate": 1.2},
    }


def test_google_reuses_a_valid_token_across_previews(minted):
    # Act
    run_adapter(synthesize, GoogleTTSConfig(credentials=_SA_JSON), _AUDIO)
    run_adapter(synthesize, GoogleTTSConfig(credentials=_SA_JSON), _AUDIO)

    # Assert
    assert len(minted) == 1
    assert minted[0].refreshes == 1
    assert minted[0].request.keywords == {"timeout": 5.0}


@pytest.mark.parametrize(
    ("credentials", "message"), [(None, "service-account"), ("{not json", "auth failed"), ("[]", "auth failed")]
)
def test_google_missing_or_invalid_credentials_raise_preview_error(minted, credentials, message):
    # Act / Assert
    with pytest.raises(PreviewProviderError, match=message):
        run_adapter(synthesize, GoogleTTSConfig(credentials=credentials), _AUDIO)


@pytest.mark.parametrize("body", [{"audioContent": ""}, {"error": "x"}])
def test_google_raises_preview_error_on_empty_or_malformed_200(minted, body):
    # Act / Assert
    with pytest.raises(PreviewProviderError):
        run_adapter(synthesize, GoogleTTSConfig(credentials=_SA_JSON), httpx.Response(200, json=body))
