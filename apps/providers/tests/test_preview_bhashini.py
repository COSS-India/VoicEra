"""Contract tests for the Bhashini TTS preview adapter (Parler gRPC and Orpheus NVCF)."""

from __future__ import annotations

import asyncio
import struct
import wave
from io import BytesIO

import grpc
import httpx
import pytest

from apps.providers.adapters.bhashini import preview, tts_pb2
from apps.providers.adapters.bhashini.config import BhashiniTTSConfig
from apps.providers.adapters.bhashini.preview import synthesize
from apps.providers.preview import PreviewProviderError
from apps.providers.tests.preview_harness import json_body, run_adapter, run_adapter_sequence, wav_sample_rate

_FUNCTION_ID = "0f0e0d0c-0b0a-4908-8706-050403020100"


def _config(**overrides: object) -> BhashiniTTSConfig:
    defaults = {
        "auth_token": "parler-token",
        "function_id": "parler-fn",
        "orpheus_auth_token": "orpheus-token",
        "orpheus_function_id": _FUNCTION_ID,
        "description": "Calm.",
    }
    return BhashiniTTSConfig(**{**defaults, **overrides})


class _FakeChannel:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


def _fake_stub(calls: list, responses=None, error: grpc.aio.AioRpcError | None = None):
    """A TTSServiceStub stand-in that records each Synthesize call and streams ``responses``."""

    async def stream():
        if error is not None:
            raise error
        for response in responses:
            yield response

    class Stub:
        def __init__(self, _channel):
            pass

        def Synthesize(self, request, metadata):  # name matches the generated stub
            calls.append((request, metadata))
            return stream()

    return Stub


@pytest.fixture
def no_network(monkeypatch):
    monkeypatch.setattr(preview.grpc.aio, "secure_channel", lambda *_args: _FakeChannel())
    monkeypatch.setattr(preview, "_NVCF_POLL_INTERVAL_S", 0)


def test_parler_converts_float_pcm_at_the_streams_own_sample_rate(no_network, monkeypatch):
    # Arrange
    calls: list = []
    responses = [
        tts_pb2.SynthesizeResponse(meta=tts_pb2.MetaFrame(sample_rate=22050)),
        tts_pb2.SynthesizeResponse(audio=tts_pb2.AudioChunk(pcm_data=struct.pack("<2f", 0.5, -2.0))),
        tts_pb2.SynthesizeResponse(done=tts_pb2.DoneFrame()),
        tts_pb2.SynthesizeResponse(audio=tts_pb2.AudioChunk(pcm_data=struct.pack("<f", 0.9))),
    ]
    monkeypatch.setattr(preview.tts_pb2_grpc, "TTSServiceStub", _fake_stub(calls, responses))

    # Act
    audio = asyncio.run(synthesize(_config(), "Namaste", None))

    # Assert: rate from the meta frame, clipped to int16, nothing read after "done".
    assert wav_sample_rate(audio) == 22050
    with wave.open(BytesIO(audio), "rb") as wf:
        assert struct.unpack("<2h", wf.readframes(2)) == (16383, -32767)
    request, metadata = calls[0]
    assert (request.prompt, request.description, request.language) == ("Namaste", "Divya Calm.", "hi")
    assert metadata == (("authorization", "Bearer parler-token"), ("function-id", "parler-fn"))


def _parler_frames(meta_rate: int, pcm: bytes) -> list:
    return [
        tts_pb2.SynthesizeResponse(meta=tts_pb2.MetaFrame(sample_rate=meta_rate)),
        tts_pb2.SynthesizeResponse(audio=tts_pb2.AudioChunk(pcm_data=pcm)),
    ]


def test_parler_keeps_the_default_rate_when_meta_reports_zero(no_network, monkeypatch):
    # Arrange
    frames = _parler_frames(0, struct.pack("<f", 0.5))
    monkeypatch.setattr(preview.tts_pb2_grpc, "TTSServiceStub", _fake_stub([], frames))

    # Act
    audio = asyncio.run(synthesize(_config(), "Namaste", None))

    # Assert
    assert wav_sample_rate(audio) == 44100


def test_parler_truncated_float32_audio_raises_preview_error(no_network, monkeypatch):
    # Arrange: 5 bytes is not a whole number of float32 samples.
    frames = _parler_frames(22050, b"\x00" * 5)
    monkeypatch.setattr(preview.tts_pb2_grpc, "TTSServiceStub", _fake_stub([], frames))

    # Act / Assert
    with pytest.raises(PreviewProviderError, match="truncated"):
        asyncio.run(synthesize(_config(), "Namaste", None))


def test_parler_grpc_error_raises_preview_error(no_network, monkeypatch):
    # Arrange
    error = grpc.aio.AioRpcError(grpc.StatusCode.UNAUTHENTICATED, grpc.aio.Metadata(), grpc.aio.Metadata())
    monkeypatch.setattr(preview.tts_pb2_grpc, "TTSServiceStub", _fake_stub([], error=error))

    # Act / Assert
    with pytest.raises(PreviewProviderError, match="UNAUTHENTICATED"):
        asyncio.run(synthesize(_config(), "Namaste", None))


def test_orpheus_polls_nvcf_status_after_202_and_wraps_pcm(no_network):
    # Arrange: only the invoke reply carries the request id, as NVCF allows.
    invoked = httpx.Response(202, headers={"NVCF-REQID": "req-1"})
    pending = httpx.Response(202)
    done = httpx.Response(200, content=b"\x00\x01" * 8)

    # Act
    audio, sent = run_adapter_sequence(
        synthesize, _config(model="orpheus", voice="Kaur", style="happy"), [invoked, pending, done], "Sat Sri Akal"
    )

    # Assert
    assert wav_sample_rate(audio) == 24000
    assert [(r.method, str(r.url)) for r in sent] == [
        ("POST", f"https://{_FUNCTION_ID}.invocation.api.nvcf.nvidia.com/v1/audio/speech"),
        ("GET", "https://api.nvcf.nvidia.com/v2/nvcf/pexec/status/req-1"),
        ("GET", "https://api.nvcf.nvidia.com/v2/nvcf/pexec/status/req-1"),
    ]
    assert all(r.headers["Authorization"] == "Bearer orpheus-token" for r in sent)
    assert json_body(sent[0]) == {
        "input": "Sat Sri Akal",
        "model": "orpheus",
        "voice": "Kaur",
        "response_format": "pcm",
        "style": "happy",
    }


@pytest.mark.parametrize("function_id", [f"{{{_FUNCTION_ID}}}", f"urn:uuid:{_FUNCTION_ID.upper()}"])
def test_orpheus_puts_the_canonical_uuid_in_the_host(no_network, function_id):
    # Act
    _, request = run_adapter(
        synthesize, _config(model="orpheus", orpheus_function_id=function_id), httpx.Response(200, content=b"\x00\x01")
    )

    # Assert
    assert request.url.host == f"{_FUNCTION_ID}.invocation.api.nvcf.nvidia.com"


@pytest.mark.parametrize(
    ("overrides", "response", "message"),
    [
        ({"orpheus_function_id": "evil.example.com/#"}, httpx.Response(200, content=b"\x00"), "UUID"),
        ({}, httpx.Response(202), "NVCF-REQID"),
        ({}, httpx.Response(200), "no audio"),
    ],
)
def test_orpheus_failures_raise_preview_error(no_network, overrides, response, message):
    # Act / Assert
    with pytest.raises(PreviewProviderError, match=message):
        run_adapter(synthesize, _config(model="orpheus", **overrides), response)


def test_unknown_bhashini_model_raises_preview_error():
    # Act / Assert
    with pytest.raises(PreviewProviderError, match="unknown model"):
        asyncio.run(synthesize(_config(model="mystery"), "hi", None))
