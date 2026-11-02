"""In-process integration tests for POST /tts/preview.

Unlike test_tts_preview_routes.py (service mocked) and test_tts_preview_service.py
(units), these run the real route, service, config validation and vendor
adapter end to end. Only the edges are faked: stored org credentials (Mongo),
the MinIO cache, the Redis rate limit and the vendor wire (httpx MockTransport,
or a fake gRPC stub for Bhashini Parler).
"""

from __future__ import annotations

import base64
import struct
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import grpc
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.providers.adapters.bhashini import preview as bhashini_preview
from apps.providers.adapters.bhashini import tts_pb2
from apps.providers.availability import register_local
from apps.providers.base import Kind
from apps.providers.local.indic_orpheus.catalog import GATEWAY_MODEL_ID as ORPHEUS_GATEWAY_ID
from apps.providers.schema import _config_class
from apps.providers.scoped_settings import resolve_settings

from app.auth import get_current_user
from app.routers import tts_preview

_SVC = "app.services.tts_preview_service"

app = FastAPI()
app.include_router(tts_preview.router, prefix="/api/v1")
app.dependency_overrides[get_current_user] = lambda: {"email": "t@example.com", "org_id": "org-1"}
client = TestClient(app)

_PARLER_ONLY_AUTH = {"api_key": "k", "auth_token": "parler-token", "function_id": "parler-fn"}
_PCM = b"\x00\x01" * 32


def _vendor_handler(request: httpx.Request) -> httpx.Response:
    """Answer any vendor TTS call with audio in the shape that vendor returns."""
    if "sarvam" in request.url.host:
        return httpx.Response(200, json={"audios": [base64.b64encode(_PCM).decode()]})
    return httpx.Response(200, content=_PCM)


def _parler_stub(calls: list, error: grpc.aio.AioRpcError | None = None):
    async def stream():
        if error is not None:
            raise error
        yield tts_pb2.SynthesizeResponse(meta=tts_pb2.MetaFrame(sample_rate=22050))
        yield tts_pb2.SynthesizeResponse(audio=tts_pb2.AudioChunk(pcm_data=struct.pack("<2f", 0.1, -0.1)))
        yield tts_pb2.SynthesizeResponse(done=tts_pb2.DoneFrame())

    class Stub:
        def __init__(self, _channel):
            pass

        def Synthesize(self, request, metadata):  # name matches the generated stub
            calls.append((request, metadata))
            return stream()

    return Stub


class _FakeChannel:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


def _preview(
    tts_config: dict,
    language: str,
    *,
    configured: list[str],
    auth: dict | None,
    handler=_vendor_handler,
    deployed: frozenset[str] = frozenset(),
) -> httpx.Response:
    """POST one preview with everything real except the faked edges."""
    real_client = httpx.AsyncClient

    def mocked_client(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    with ExitStack() as stack:
        for target, value in [
            (f"{_SVC}.auth_service.list_configured_providers", lambda _org: configured),
            (f"{_SVC}.auth_service.get_provider_auth", lambda _org, _p: {"auth": auth} if auth else None),
            (f"{_SVC}.get_cached", AsyncMock(return_value=None)),
            (f"{_SVC}.put_cached", AsyncMock()),
            (f"{_SVC}.check_rate_limit", AsyncMock()),
            (f"{_SVC}.httpx.AsyncClient", mocked_client),
            ("apps.providers.availability._deployed_ids", lambda: deployed),
        ]:
            stack.enter_context(patch(target, value))
        return client.post(
            "/api/v1/tts/preview",
            json={"tts_config": tts_config, "language": language, "text": "Namaste {{name}}"},
        )


@pytest.fixture
def parler_wire(monkeypatch):
    """Fake the Parler gRPC channel; returns the list of captured Synthesize calls."""
    calls: list = []
    monkeypatch.setattr(bhashini_preview.grpc.aio, "secure_channel", lambda *_args: _FakeChannel())
    monkeypatch.setattr(bhashini_preview.tts_pb2_grpc, "TTSServiceStub", _parler_stub(calls))
    return calls


_TICKET_CONFIG = {"provider": "bhashini", "model": "bhashini-indic-parler", "voice": "Rohit"}


# --- AC1: the ticket's selection previews with the creds the org could save ---


def test_bhashini_parler_rohit_with_parler_only_creds_returns_audio(parler_wire):
    response = _preview(_TICKET_CONFIG, "hi", configured=["bhashini"], auth=_PARLER_ONLY_AUTH)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "audio/wav"
    assert response.content.startswith(b"RIFF")
    request, metadata = parler_wire[0]
    assert request.prompt == "Namaste"
    assert request.description.startswith("Rohit ")
    assert metadata == (("authorization", "Bearer parler-token"), ("function-id", "parler-fn"))


@pytest.mark.parametrize("voice", ["Rohit", "Divya", "Aman", "Rani"])
def test_every_hindi_parler_voice_previews(parler_wire, voice):
    response = _preview(
        {**_TICKET_CONFIG, "voice": voice}, "hi", configured=["bhashini"], auth=_PARLER_ONLY_AUTH
    )

    assert response.status_code == 200, response.text


# --- AC2: vendor / network failures say so, never "invalid configuration" ---


def test_bhashini_grpc_failure_is_upstream_not_invalid_config(monkeypatch):
    error = grpc.aio.AioRpcError(grpc.StatusCode.UNAVAILABLE, grpc.aio.Metadata(), grpc.aio.Metadata())
    monkeypatch.setattr(bhashini_preview.grpc.aio, "secure_channel", lambda *_args: _FakeChannel())
    monkeypatch.setattr(bhashini_preview.tts_pb2_grpc, "TTSServiceStub", _parler_stub([], error))

    response = _preview(_TICKET_CONFIG, "hi", configured=["bhashini"], auth=_PARLER_ONLY_AUTH)

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "upstream"


def test_bhashini_orpheus_without_orpheus_creds_is_upstream_not_invalid_config():
    response = _preview(
        {"provider": "bhashini", "model": "orpheus", "voice": "Amit"},
        "hi",
        configured=["bhashini"],
        auth=_PARLER_ONLY_AUTH,
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "upstream"


def _connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("unreachable", request=request)


def _server_error(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(500)


@pytest.mark.parametrize("handler", [_connect_error, _server_error], ids=["network", "http-500"])
def test_cloud_vendor_failure_is_upstream(handler):
    response = _preview(
        {"provider": "openai", "model": "gpt-4o-mini-tts", "voice": "alloy"},
        "en",
        configured=["openai"],
        auth={"api_key": "sk-test"},
        handler=handler,
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "upstream"


def test_incomplete_stored_creds_is_not_configured_not_invalid_config():
    response = _preview(
        {"provider": "sarvam", "model": "bulbul:v3", "voice": "shubh"},
        "hi",
        configured=["sarvam"],
        auth={"unrelated": "x"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_configured"


def test_voice_outside_the_list_is_still_rejected():
    response = _preview(
        {**_TICKET_CONFIG, "voice": "Nobody"}, "hi", configured=["bhashini"], auth=_PARLER_ONLY_AUTH
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_voice"


# --- AC3: other providers, each model with its default voice ---


def _default_cases(provider: str) -> list[tuple[str, str, str, str]]:
    """(provider, model, language, default voice) for every model's first language."""
    tree = _config_class(Kind.TTS, provider).settings_by_model_language
    cases = []
    for model, by_lang in tree.items():
        language = next(iter(by_lang))
        voice = (resolve_settings(tree, model, language).get("voice") or {}).get("default")
        cases.append((provider, model, language, voice))
    return cases


_CLOUD_CASES = [
    case
    for provider in ("cartesia", "deepgram", "elevenlabs", "openai", "sarvam")
    for case in _default_cases(provider)
]


@pytest.mark.parametrize(
    ("provider", "model", "language", "voice"), _CLOUD_CASES, ids=[f"{c[0]}-{c[1]}" for c in _CLOUD_CASES]
)
def test_cloud_provider_default_voice_previews(provider, model, language, voice):
    response = _preview(
        {"provider": provider, "model": model, "voice": voice},
        language,
        configured=[provider],
        auth={"api_key": "test-key"},
    )

    assert response.status_code == 200, response.text
    assert response.content


def test_local_indic_orpheus_previews_when_model_server_serves_it(monkeypatch):
    register_local("indic_orpheus", ORPHEUS_GATEWAY_ID)
    monkeypatch.setenv("MODEL_SERVER_URL", "http://model-server.test/v1")
    (_, model, language, voice), *_ = _default_cases("indic_orpheus")

    response = _preview(
        {"provider": "indic_orpheus", "model": model, "voice": voice},
        language,
        configured=[],
        auth=None,
        deployed=frozenset({ORPHEUS_GATEWAY_ID}),
    )

    assert response.status_code == 200, response.text


def test_local_indic_orpheus_not_served_is_not_configured():
    register_local("indic_orpheus", ORPHEUS_GATEWAY_ID)
    (_, model, language, voice), *_ = _default_cases("indic_orpheus")

    response = _preview(
        {"provider": "indic_orpheus", "model": model, "voice": voice},
        language,
        configured=[],
        auth=None,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_configured"
