"""Optional live integration tests for POST /tts/preview.

Unlike test_tts_preview_integration.py (vendor wire faked), these hit the
running API over HTTP, which calls the real vendors with the org's stored
credentials. Each configured provider costs one short real synthesis.

    set -a; source .env; set +a
    RUN_TTS_PREVIEW_INTEGRATION=1 TEST_ORG_ID=<org_id> \\
    python -m pytest apps/api/tests/test_tts_preview_live_integration.py -q

When the org has no Bhashini credentials, the Bhashini checks store
Parler-only placeholder creds (what the Integrations page lets an org save),
expect the real Bhashini endpoint to reject them as an upstream error, and
delete them afterwards. With real Bhashini creds stored, they expect audio.

Optional: API_BASE_URL (default http://localhost:8000/api/v1).
"""

from __future__ import annotations

import os

import httpx
import pytest

from apps.providers.base import Kind
from apps.providers.schema import _config_class
from apps.providers.scoped_settings import resolve_settings

RUN_INTEGRATION = os.getenv("RUN_TTS_PREVIEW_INTEGRATION", "").strip().lower() in {"1", "true", "yes"}
TEST_ORG_ID = os.getenv("TEST_ORG_ID", "")
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not (RUN_INTEGRATION and TEST_ORG_ID and INTERNAL_API_KEY),
    reason="Set RUN_TTS_PREVIEW_INTEGRATION=1, TEST_ORG_ID and INTERNAL_API_KEY to run live preview tests",
)

_TICKET_CONFIG = {"provider": "bhashini", "model": "bhashini-indic-parler", "voice": "Rohit"}
_PLACEHOLDER_PARLER_AUTH = {"api_key": "it-placeholder", "auth_token": "it-placeholder", "function_id": "it-placeholder"}


@pytest.fixture(scope="module")
def api() -> httpx.Client:
    token = httpx.post(
        f"{API_BASE}/users/bot/token",
        headers={"X-API-Key": INTERNAL_API_KEY},
        json={"org_id": TEST_ORG_ID},
        timeout=30.0,
    )
    token.raise_for_status()
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
    with httpx.Client(base_url=API_BASE, headers=headers, timeout=60.0) as client:
        yield client


@pytest.fixture(scope="module")
def configured(api: httpx.Client) -> list[str]:
    response = api.get("/auth/configured")
    response.raise_for_status()
    return response.json()


@pytest.fixture(scope="module")
def bhashini_creds(api: httpx.Client, configured: list[str]):
    """Yield True when the org has real Bhashini creds; else store placeholders and remove them after."""
    if "bhashini" in configured:
        yield True
        return
    api.post("/auth", json={"provider": "bhashini", "auth": _PLACEHOLDER_PARLER_AUTH}).raise_for_status()
    try:
        yield False
    finally:
        api.delete("/auth/bhashini")


def _preview(api: httpx.Client, tts_config: dict, language: str) -> httpx.Response:
    return api.post(
        "/tts/preview",
        json={"tts_config": tts_config, "language": language, "text": "Namaste, this is a voice preview."},
    )


def test_bhashini_parler_rohit_is_never_reported_as_invalid_config(api, bhashini_creds):
    response = _preview(api, _TICKET_CONFIG, "hi")

    if bhashini_creds:  # AC1: real creds → audio
        assert response.status_code == 200, response.text
        assert response.content.startswith(b"RIFF")
    else:  # AC2: Bhashini rejects placeholder creds → a vendor error, not "invalid config"
        assert response.status_code in (502, 504), response.text
        assert response.json()["detail"]["code"] in ("upstream", "timeout")


def _default_voice(provider: str) -> tuple[str, str, str]:
    tree = _config_class(Kind.TTS, provider).settings_by_model_language
    model, by_lang = next(iter(tree.items()))
    language = next(iter(by_lang))
    return model, language, (resolve_settings(tree, model, language).get("voice") or {}).get("default")


@pytest.mark.parametrize("provider", ["cartesia", "deepgram", "elevenlabs", "openai", "sarvam"])
def test_configured_provider_default_voice_returns_audio(api, configured, provider):
    if provider not in configured:
        pytest.skip(f"{provider} not configured for org {TEST_ORG_ID}")
    model, language, voice = _default_voice(provider)

    response = _preview(api, {"provider": provider, "model": model, "voice": voice}, language)

    # AC3: a configured provider with its default voice still previews.
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "audio/wav"
    assert len(response.content) > 1000
