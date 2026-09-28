"""Tests for Kenpath DLS LLM adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from pipecat.frames.frames import (
    EndWorkerFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from apps.providers.adapters.kenpath_dls.catalog import (
    DEFAULT_LLM_MODEL,
    DEFAULT_URL,
    VOICE_DLS_PATH,
)
from apps.providers.adapters.kenpath_dls.config import KenpathDlsLLMConfig
from apps.providers.adapters.kenpath_dls.language_markers import (
    extract_lang_marker,
    flush_speakable,
    strip_lang_marker_for_tts,
    wire_to_canonical,
)
from apps.providers.adapters.kenpath_dls.llm import KenpathDlsLLMService
from apps.runtime.services.language_switch.frames import LanguageSwitchFrame

_TEST_PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF8PbnGy0AHB7MZpHmaFjdNT4zLmg
7cHZnn2qgQNO2gHr2x5mH7Vb2f9lP4mJ8nQ6sT1uV3wX5yZ7aB9cD1eF3gH5iJ7k
L9mN1oP3qR5sT7uV9wX1yZ3aB5cD7eF9gH1iJ3kL5mN7oP9qR1sT3uV5wX7yZ9aB
1cD3eF5gH7iJ9kL1mN3oP5qR7sT9uV1wX3yZ5aB7cD9eF1gH3iJ5kL7mN9oP1qR3
sT5uV7wX9yZ1aB3cD5eF7gH9iJ1kL3mN5oP7qR9sT1uV3wX5yZ7aB9cD1eF3gH5iJ7
kL9mN1oP3qR5sT7uV9wX1yZ3aB5cD7eF9gH1iJ3kL5mN7oP9qR1sT3uV5wX7yZ9aB
1cD3eF5gH7iJ9kL1mN3oP5qR7sT9uV1wX3yZ5aB7cD9eF1gH3iJ5kL7mN9oP1qR3
sT5uV7wX9yZ1aB3cD5eF7gH9iJ1kL3mN5oP7qR9sT1uV3wX5yZ7aB9cD1eF3gH5iJ7
kQIDAQABAoIBADxmockkeypaddingnotavalidrsakeyforproductionuseonly==
-----END RSA PRIVATE KEY-----"""


@pytest.fixture
def service() -> KenpathDlsLLMService:
    return KenpathDlsLLMService(
        private_key=_TEST_PRIVATE_KEY,
        jwt_sub="+91-9000000000",
        base_url=DEFAULT_URL,
        model=DEFAULT_LLM_MODEL,
    )


def test_wire_to_canonical():
    assert wire_to_canonical("mr") == "mr"
    assert wire_to_canonical("bhb") == "bh"
    assert wire_to_canonical("BHB") == "bh"


def test_extract_and_strip_lang_marker():
    assert extract_lang_marker("hello") is None
    assert extract_lang_marker("<lang:mr> नमस्कार") == "mr"
    assert extract_lang_marker("<lang:bhb> hello") == "bhb"
    assert strip_lang_marker_for_tts("<lang:mr> नमस्कार ") == "नमस्कार "
    assert strip_lang_marker_for_tts("plain text") == "plain text"


def test_flush_speakable_holds_incomplete_marker():
    speakable, hold = flush_speakable("hi <lang:m")
    assert speakable == "hi "
    assert hold == "<lang:m"
    speakable2, hold2 = flush_speakable(hold + "r> rest ")
    assert "<lang" not in speakable2 or "lang:mr" in speakable2 + hold2
    full = strip_lang_marker_for_tts(speakable2 + hold2)
    assert "rest" in full
    assert "lang" not in full


def test_create_llm_requires_private_key():
    from apps.providers.adapters.kenpath_dls.service import create_llm

    cfg = KenpathDlsLLMConfig.model_validate({"model": DEFAULT_LLM_MODEL})
    with pytest.raises(ValueError, match="private_key"):
        create_llm(cfg)


def test_create_llm_uses_catalog_base_url():
    from apps.providers.adapters.kenpath_dls.service import create_llm

    cfg = KenpathDlsLLMConfig.model_validate(
        {
            "private_key": _TEST_PRIVATE_KEY,
            "jwt_sub": "+91-9000000000",
            "model": DEFAULT_LLM_MODEL,
        }
    )
    svc = create_llm(cfg)
    assert isinstance(svc, KenpathDlsLLMService)
    assert svc._base_url == DEFAULT_URL.rstrip("/")
    assert svc._private_key == _TEST_PRIVATE_KEY
    assert svc._jwt_sub == "+91-9000000000"


def test_create_llm_base_url_override():
    from apps.providers.adapters.kenpath_dls.service import create_llm

    cfg = KenpathDlsLLMConfig.model_validate(
        {
            "private_key": _TEST_PRIVATE_KEY,
            "base_url": "https://custom.example/",
            "model": DEFAULT_LLM_MODEL,
        }
    )
    svc = create_llm(cfg)
    assert svc._base_url == "https://custom.example"


def test_generate_jwt_payload(service: KenpathDlsLLMService, monkeypatch):
    captured: dict = {}

    def fake_encode(payload, key, algorithm):
        captured["payload"] = payload
        captured["key"] = key
        captured["algorithm"] = algorithm
        return "signed-token"

    monkeypatch.setattr(jwt, "encode", fake_encode)
    token = service._generate_jwt()
    assert token == "signed-token"
    assert captured["algorithm"] == "RS256"
    assert captured["key"] == _TEST_PRIVATE_KEY
    assert captured["payload"]["sub"] == "+91-9000000000"
    assert captured["payload"]["iss"] == "voice-provider"
    assert "iat" in captured["payload"]
    assert "exp" in captured["payload"]


@pytest.mark.asyncio
async def test_stream_voice_dls_uses_session_id(
    service: KenpathDlsLLMService, monkeypatch
):
    monkeypatch.setattr(jwt, "encode", lambda *args, **kwargs: "signed-token")
    service.set_call_id("dls-call-1")

    stream_cm = AsyncMock()
    response = AsyncMock()
    response.status_code = 200

    async def aiter_bytes():
        yield b"hello world"

    response.aiter_bytes = aiter_bytes
    stream_cm.__aenter__.return_value = response
    stream_cm.__aexit__.return_value = None

    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.stream.return_value = stream_cm
    service._client = mock_client

    chunks = [chunk async for chunk in service._stream_voice_dls("namaste")]
    assert chunks == ["hello ", "world"]

    mock_client.stream.assert_called_once()
    call_args = mock_client.stream.call_args
    assert call_args.args[0] == "GET"
    assert call_args.args[1] == f"{DEFAULT_URL.rstrip('/')}{VOICE_DLS_PATH}"
    assert call_args.kwargs["params"]["session_id"] == "dls-call-1"
    assert call_args.kwargs["params"]["query"] == "namaste"
    assert call_args.kwargs["headers"]["Authorization"] == "Bearer signed-token"


@pytest.mark.asyncio
async def test_stream_voice_dls_non_200_raises(
    service: KenpathDlsLLMService, monkeypatch
):
    monkeypatch.setattr(jwt, "encode", lambda *args, **kwargs: "signed-token")
    stream_cm = AsyncMock()
    response = AsyncMock()
    response.status_code = 500
    response.aread = AsyncMock(return_value=b"server error")
    stream_cm.__aenter__.return_value = response
    stream_cm.__aexit__.return_value = None

    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.stream.return_value = stream_cm
    service._client = mock_client

    with pytest.raises(RuntimeError, match="Kenpath DLS API Error 500"):
        async for _ in service._stream_voice_dls("test"):
            pass


@pytest.mark.asyncio
async def test_lang_marker_queues_switch_frame_and_strips_tts(
    service: KenpathDlsLLMService, monkeypatch
):
    monkeypatch.setattr(jwt, "encode", lambda *args, **kwargs: "signed-token")
    stream_cm = AsyncMock()
    response = AsyncMock()
    response.status_code = 200

    async def aiter_bytes():
        yield b"<lang:mr> hello there"

    response.aiter_bytes = aiter_bytes
    stream_cm.__aenter__.return_value = response
    stream_cm.__aexit__.return_value = None

    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.stream.return_value = stream_cm
    service._client = mock_client

    worker = MagicMock()
    worker.queue_frame = AsyncMock()
    setup = MagicMock()
    setup.pipeline_worker = worker
    setup.observer = None
    service._setup = setup

    pushed: list = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    service.push_frame = capture  # type: ignore[method-assign]
    service._push_llm_text = AsyncMock()  # type: ignore[method-assign]
    service.start_processing_metrics = AsyncMock()  # type: ignore[method-assign]
    service.stop_processing_metrics = AsyncMock()  # type: ignore[method-assign]
    service.start_ttfb_metrics = AsyncMock()  # type: ignore[method-assign]
    service.stop_ttfb_metrics = AsyncMock()  # type: ignore[method-assign]

    context = LLMContext(messages=[{"role": "user", "content": "marathi"}])
    await service.process_frame(LLMContextFrame(context=context), FrameDirection.DOWNSTREAM)

    worker.queue_frame.assert_awaited()
    frame, direction = worker.queue_frame.await_args.args
    assert isinstance(frame, LanguageSwitchFrame)
    assert frame.language == "mr"
    assert direction == FrameDirection.DOWNSTREAM

    spoken = "".join(
        call.args[0] for call in service._push_llm_text.await_args_list
    )
    assert "lang" not in spoken.lower()
    assert "hello" in spoken
    assert any(isinstance(f, LLMFullResponseStartFrame) for f in pushed)
    assert any(isinstance(f, LLMFullResponseEndFrame) for f in pushed)


@pytest.mark.asyncio
async def test_bhb_marker_maps_to_canonical_bh(
    service: KenpathDlsLLMService, monkeypatch
):
    monkeypatch.setattr(jwt, "encode", lambda *args, **kwargs: "signed-token")
    stream_cm = AsyncMock()
    response = AsyncMock()
    response.status_code = 200

    async def aiter_bytes():
        yield b"<lang:bhb> bhili reply"

    response.aiter_bytes = aiter_bytes
    stream_cm.__aenter__.return_value = response
    stream_cm.__aexit__.return_value = None

    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.stream.return_value = stream_cm
    service._client = mock_client

    worker = MagicMock()
    worker.queue_frame = AsyncMock()
    setup = MagicMock()
    setup.pipeline_worker = worker
    setup.observer = None
    service._setup = setup

    service.push_frame = AsyncMock()  # type: ignore[method-assign]
    service._push_llm_text = AsyncMock()  # type: ignore[method-assign]
    service.start_processing_metrics = AsyncMock()  # type: ignore[method-assign]
    service.stop_processing_metrics = AsyncMock()  # type: ignore[method-assign]
    service.start_ttfb_metrics = AsyncMock()  # type: ignore[method-assign]
    service.stop_ttfb_metrics = AsyncMock()  # type: ignore[method-assign]

    context = LLMContext(messages=[{"role": "user", "content": "bhili"}])
    await service.process_frame(LLMContextFrame(context=context), FrameDirection.DOWNSTREAM)

    frame, _ = worker.queue_frame.await_args.args
    assert isinstance(frame, LanguageSwitchFrame)
    assert frame.language == "bh"


@pytest.mark.asyncio
async def test_goodbye_pushes_end_worker_after_response(
    service: KenpathDlsLLMService, monkeypatch
):
    monkeypatch.setattr(jwt, "encode", lambda *args, **kwargs: "signed-token")
    stream_cm = AsyncMock()
    response = AsyncMock()
    response.status_code = 200

    async def aiter_bytes():
        yield b"goodbye"

    response.aiter_bytes = aiter_bytes
    stream_cm.__aenter__.return_value = response
    stream_cm.__aexit__.return_value = None

    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.stream.return_value = stream_cm
    service._client = mock_client

    pushed: list = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    service.push_frame = capture  # type: ignore[method-assign]
    service._push_llm_text = AsyncMock()  # type: ignore[method-assign]
    service.start_processing_metrics = AsyncMock()  # type: ignore[method-assign]
    service.stop_processing_metrics = AsyncMock()  # type: ignore[method-assign]
    service.start_ttfb_metrics = AsyncMock()  # type: ignore[method-assign]
    service.stop_ttfb_metrics = AsyncMock()  # type: ignore[method-assign]

    context = LLMContext(messages=[{"role": "user", "content": "bye"}])
    await service.process_frame(LLMContextFrame(context=context), FrameDirection.DOWNSTREAM)

    service._push_llm_text.assert_not_called()
    end_idxs = [i for i, f in enumerate(pushed) if isinstance(f, LLMFullResponseEndFrame)]
    worker_idxs = [i for i, f in enumerate(pushed) if isinstance(f, EndWorkerFrame)]
    assert end_idxs and worker_idxs
    assert worker_idxs[0] > end_idxs[0]
