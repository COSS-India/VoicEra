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


def test_deployed_llm_model_ids_filters_by_kind_and_deployed_status(monkeypatch):
    """GET /models returns model-server's full catalogue — every model of
    every kind (stt/tts/llm), deployed or not — not just what's callable
    right now. A caller resolving the actual deployed LLM model name (e.g.
    to put in a chat-completion request) must filter to kind=="llm" and
    deployed==True, or it can just as easily pick an STT/TTS id or an
    undeployed LLM catalogue entry."""
    monkeypatch.setenv("MODEL_SERVER_URL", "http://gateway:8000/v1")
    body = json.dumps(
        {
            "object": "list",
            "data": [
                {"id": "whisper-large", "kind": "stt", "deployed": True},
                {"id": "indic-tts-v2", "kind": "tts", "deployed": True},
                {"id": "gemma-3-4b", "kind": "llm", "deployed": True},
                {"id": "qwen3.5-4b", "kind": "llm", "deployed": False},
            ],
        }
    ).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert availability.deployed_llm_model_ids() == frozenset({"gemma-3-4b"})


def test_deployed_llm_model_ids_and_is_authenticated_share_one_cached_fetch(monkeypatch):
    """Both views read from the same 10s cache — calling one must not force
    a second HTTP round-trip for the other within the cache window."""
    monkeypatch.setenv("MODEL_SERVER_URL", "http://gateway:8000/v1")
    availability.register_local("indic_nemotron", "indic-nemotron")
    body = json.dumps(
        {
            "object": "list",
            "data": [
                {"id": "indic-nemotron", "kind": "tts", "deployed": True},
                {"id": "gemma-3-4b", "kind": "llm", "deployed": True},
            ],
        }
    ).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    with patch("urllib.request.urlopen", return_value=mock_resp) as urlopen:
        assert availability.is_authenticated("indic_nemotron", set()) is True
        assert availability.deployed_llm_model_ids() == frozenset({"gemma-3-4b"})
        assert urlopen.call_count == 1
