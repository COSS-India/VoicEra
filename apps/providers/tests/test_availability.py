"""Local provider readiness / authenticated helper."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.providers import availability


@pytest.fixture(autouse=True)
def _reset_availability():
    saved = dict(availability.LOCAL_GATEWAY_MODELS)
    availability.clear_local_registrations()
    yield
    availability.clear_local_registrations()
    availability.LOCAL_GATEWAY_MODELS.update(saved)


def test_cloud_uses_configured_set():
    assert availability.is_authenticated("deepgram", {"deepgram"}) is True
    assert availability.is_authenticated("deepgram", set()) is False


def test_platform_credentials_authenticate_a_cloud_provider():
    assert availability.is_authenticated("deepgram", set(), {"deepgram"}) is True
    assert availability.auth_source("deepgram", set(), {"deepgram"}) == "platform"


def test_auth_source_precedence_is_local_then_org_then_platform():
    availability.register_local("indic_nemotron", "indic-nemotron")
    assert availability.auth_source(
        "indic_nemotron", {"indic_nemotron"}, {"indic_nemotron"}
    ) == "local"
    # An org that brought its own key reads as "Connected", not "Included".
    assert availability.auth_source("openai", {"openai"}, {"openai"}) == "org"
    assert availability.auth_source("openai", set(), set()) is None


def test_local_needs_no_credentials_or_env(monkeypatch):
    """Ships with the deployment: free for every org, nothing to configure."""
    monkeypatch.delenv("MODEL_SERVER_URL", raising=False)
    availability.register_local("indic_nemotron", "indic-nemotron")
    availability.register_local("indic_orpheus", "orpheus")
    assert availability.is_authenticated("indic_nemotron", set()) is True
    assert availability.is_authenticated("indic_orpheus", set()) is True


def test_local_availability_does_not_probe_the_model_server():
    """The gateway being briefly down must not hide a bundled provider."""
    availability.register_local("indic_nemotron", "indic-nemotron")
    with patch("urllib.request.urlopen", side_effect=AssertionError("probed")):
        assert availability.is_authenticated("indic_nemotron", set()) is True


def test_unregistered_provider_is_not_local():
    assert availability.auth_source("indic_orpheus", set(), set()) is None
