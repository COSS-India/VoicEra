"""Local provider readiness / authenticated helper."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

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


def test_local_missing_env_is_false(monkeypatch):
    monkeypatch.delenv("MODEL_SERVER_URL", raising=False)
    availability.register_local("indic_nemotron", "indic-nemotron")
    assert availability.is_authenticated("indic_nemotron", set()) is False


def test_local_model_present(monkeypatch):
    monkeypatch.setenv("MODEL_SERVER_URL", "http://gateway:8000/v1")
    availability.register_local("indic_nemotron", "indic-nemotron")
    body = json.dumps(
        {
            "object": "list",
            "data": [{"id": "indic-nemotron", "object": "model"}],
        }
    ).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    with patch("urllib.request.urlopen", return_value=mock_resp) as urlopen:
        assert availability.is_authenticated("indic_nemotron", set()) is True
        urlopen.assert_called_once()
        assert urlopen.call_args.args[0] == "http://gateway:8000/v1/models"


def test_local_model_absent(monkeypatch):
    monkeypatch.setenv("MODEL_SERVER_URL", "http://gateway:8000/v1")
    availability.register_local("indic_orpheus", "orpheus")
    body = json.dumps(
        {"object": "list", "data": [{"id": "indic-nemotron"}]}
    ).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert availability.is_authenticated("indic_orpheus", set()) is False


def test_local_probe_failure_is_false(monkeypatch):
    monkeypatch.setenv("MODEL_SERVER_URL", "http://gateway:8000/v1")
    availability.register_local("indic_nemotron", "indic-nemotron")
    with patch("urllib.request.urlopen", side_effect=TimeoutError):
        assert availability.is_authenticated("indic_nemotron", set()) is False


def test_deployed_ids_are_cached(monkeypatch):
    monkeypatch.setenv("MODEL_SERVER_URL", "http://gateway:8000/v1")
    availability.register_local("indic_nemotron", "indic-nemotron")
    body = json.dumps(
        {"object": "list", "data": [{"id": "indic-nemotron"}]}
    ).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    with patch("urllib.request.urlopen", return_value=mock_resp) as urlopen:
        assert availability.is_authenticated("indic_nemotron", set()) is True
        assert availability.is_authenticated("indic_nemotron", set()) is True
        assert urlopen.call_count == 1
