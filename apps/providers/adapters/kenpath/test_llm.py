"""Tests for Kenpath Vistaar / Bharat Vistaar LLM adapter."""

from __future__ import annotations

import codecs
import json
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest

from apps.providers.adapters.kenpath.catalog import (
    BHARAT_VISTAAR_CHAT_MODEL,
    BHARAT_VISTAAR_DEV_AUTH_SECRET,
    BHARAT_VISTAAR_DEV_MODEL,
    BHARAT_VISTAAR_DEV_PATH,
    BHARAT_VISTAAR_JWT_ISS,
    BHARAT_VISTAAR_PROD_AUTH_SECRET,
    BHARAT_VISTAAR_PROD_MODEL,
    BHARAT_VISTAAR_PROD_PATH,
    DEFAULT_BHARAT_VISTAAR_DEV_URL,
    DEFAULT_BHARAT_VISTAAR_PROD_URL,
    DEFAULT_VOICE_BHILI_DEV_URL,
    DEFAULT_VOICE_BHILI_PROD_URL,
    MODEL_VOICE_BHILI_URLS,
    VISTAAR_AUTH_SECRET,
    VISTAAR_DEV_MODEL,
    VISTAAR_PROD_MODEL,
    resolve_auth_secret,
    resolve_backend,
    resolve_base_url,
    resolve_completions_path,
    resolve_languages,
)
from apps.providers.adapters.kenpath.call_ending import (
    end_call,
    response_requests_end_call,
    strip_goodbye_for_tts,
)
from apps.providers.adapters.kenpath.config import KenpathLLMConfig
from apps.providers.adapters.kenpath.bharat_vistaar_llm import (
    BharatVistaarLLMService,
    bharat_vistaar_audio_suffix,
    parse_bharat_vistaar_voice_delta,
)
from apps.providers.adapters.kenpath.llm import (
    KenpathLLMService,
    extract_last_user_message,
    yield_word_chunks_from_text,
)
from pipecat.frames.frames import (
    EndWorkerFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection


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
def service() -> KenpathLLMService:
    return KenpathLLMService(
        private_key=_TEST_PRIVATE_KEY,
        jwt_sub="+91-9000000000",
        base_url="https://vistaar-dev.mahapocra.gov.in",
        model=VISTAAR_DEV_MODEL,
        source_lang="mr",
        target_lang="mr",
        backend="vistaar",
    )


def test_resolve_base_url_from_model():
    assert resolve_base_url(VISTAAR_PROD_MODEL) == "https://voice-prod.mahapocra.gov.in"
    assert resolve_base_url(BHARAT_VISTAAR_PROD_MODEL) == DEFAULT_BHARAT_VISTAAR_PROD_URL
    assert resolve_base_url(BHARAT_VISTAAR_DEV_MODEL) == DEFAULT_BHARAT_VISTAAR_DEV_URL


def test_resolve_base_url_override():
    url = resolve_base_url(VISTAAR_PROD_MODEL, "https://custom.example/")
    assert url == "https://custom.example"


def test_resolve_base_url_unknown_model():
    with pytest.raises(ValueError, match="Unknown Kenpath model"):
        resolve_base_url("unknown-model")


def test_resolve_backend_and_paths():
    assert resolve_backend(VISTAAR_PROD_MODEL) == "vistaar"
    assert resolve_backend(BHARAT_VISTAAR_PROD_MODEL) == "bharatvistaar"
    assert resolve_completions_path(BHARAT_VISTAAR_PROD_MODEL) == BHARAT_VISTAAR_PROD_PATH
    assert resolve_completions_path(BHARAT_VISTAAR_DEV_MODEL) == BHARAT_VISTAAR_DEV_PATH
    with pytest.raises(ValueError, match="no Bharat completions path"):
        resolve_completions_path(VISTAAR_PROD_MODEL)


def test_resolve_auth_secret():
    assert resolve_auth_secret(VISTAAR_PROD_MODEL) == VISTAAR_AUTH_SECRET
    assert resolve_auth_secret(VISTAAR_DEV_MODEL) == "private_key"
    assert resolve_auth_secret(BHARAT_VISTAAR_PROD_MODEL) == BHARAT_VISTAAR_PROD_AUTH_SECRET
    assert resolve_auth_secret(BHARAT_VISTAAR_DEV_MODEL) == BHARAT_VISTAAR_DEV_AUTH_SECRET
    assert resolve_auth_secret(BHARAT_VISTAAR_PROD_MODEL) == "bharat_prod_private_key"
    assert resolve_auth_secret(BHARAT_VISTAAR_DEV_MODEL) == "bharat_dev_private_key"


def test_resolve_languages():
    assert resolve_languages(VISTAAR_DEV_MODEL) == ("mr", "bhb")
    assert resolve_languages(BHARAT_VISTAAR_PROD_MODEL) == ("en", "hi")
    assert "mr" in resolve_languages(BHARAT_VISTAAR_DEV_MODEL)


def test_voice_bhili_urls_are_catalogued_per_model():
    assert MODEL_VOICE_BHILI_URLS[VISTAAR_PROD_MODEL] == DEFAULT_VOICE_BHILI_PROD_URL
    assert MODEL_VOICE_BHILI_URLS[VISTAAR_DEV_MODEL] == DEFAULT_VOICE_BHILI_DEV_URL
    assert BHARAT_VISTAAR_PROD_MODEL not in MODEL_VOICE_BHILI_URLS
    assert DEFAULT_VOICE_BHILI_PROD_URL.endswith("/api/voice-bhili/")
    assert DEFAULT_VOICE_BHILI_DEV_URL.endswith("/api/voice-bhili/")


def test_yield_word_chunks_from_text():
    assert list(yield_word_chunks_from_text("hello world")) == ["hello ", "world"]


def test_extract_last_user_message():
    context = MagicMock()
    context.get_messages.return_value = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "latest question"},
    ]
    assert extract_last_user_message(context) == "latest question"


def test_parse_bharat_vistaar_voice_delta():
    assert parse_bharat_vistaar_voice_delta("hello") == ("hello", False)
    audio, end = parse_bharat_vistaar_voice_delta(
        json.dumps({"audio": "namaste", "end_interaction": True, "language": "hi"})
    )
    assert audio == "namaste"
    assert end is True


def test_bharat_vistaar_audio_suffix():
    assert bharat_vistaar_audio_suffix("hello world", "") == ("hello world", "hello world")
    assert bharat_vistaar_audio_suffix("hello world", "hello ") == ("world", "hello world")
    assert bharat_vistaar_audio_suffix("hello ", "hello ") == ("", "hello ")


def test_set_call_id_used_as_session_id(service: KenpathLLMService):
    service.set_call_id("call-abc-123")
    assert service._session_id() == "call-abc-123"


def test_generate_jwt_payload(service: KenpathLLMService, monkeypatch):
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


def test_generate_bharat_vistaar_jwt_payload(monkeypatch):
    captured: dict = {}

    def fake_encode(payload, key, algorithm):
        captured["payload"] = payload
        return "bharat-token"

    monkeypatch.setattr(jwt, "encode", fake_encode)
    service = BharatVistaarLLMService(
        private_key=_TEST_PRIVATE_KEY,
        base_url=DEFAULT_BHARAT_VISTAAR_PROD_URL,
        completions_path=BHARAT_VISTAAR_PROD_PATH,
        model=BHARAT_VISTAAR_PROD_MODEL,
        source_lang="hi",
    )
    service.set_call_id("call-bh-1")
    token = service._generate_jwt()
    assert token == "bharat-token"
    assert captured["payload"]["iss"] == BHARAT_VISTAAR_JWT_ISS
    assert captured["payload"]["user_id"] == "call-bh-1"
    assert captured["payload"]["tenant_id"] == "call-bh-1"


@pytest.mark.asyncio
async def test_stream_vistaar_completions_uses_call_id(
    service: KenpathLLMService, monkeypatch
):
    monkeypatch.setattr(jwt, "encode", lambda *args, **kwargs: "signed-token")
    service.set_call_id("call-xyz")

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

    chunks = [chunk async for chunk in service._stream_vistaar_completions("namaste")]
    assert chunks == ["hello ", "world"]

    mock_client.stream.assert_called_once()
    call_kwargs = mock_client.stream.call_args.kwargs
    assert call_kwargs["params"]["session_id"] == "call-xyz"
    assert call_kwargs["params"]["query"] == "namaste"
    assert call_kwargs["params"]["source_lang"] == "mr"
    assert call_kwargs["headers"]["Authorization"] == "Bearer signed-token"


@pytest.mark.asyncio
async def test_stream_vistaar_completions_non_200_raises(
    service: KenpathLLMService, monkeypatch
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

    with pytest.raises(RuntimeError, match="Vistaar API Error 500"):
        async for _ in service._stream_vistaar_completions("test"):
            pass


def test_incremental_utf8_decode_matches_reference_pattern():
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    part1 = decoder.decode("hello ".encode("utf-8"), final=False)
    part2 = decoder.decode("world".encode("utf-8"), final=False)
    part3 = decoder.decode(b"", final=True)
    assert part1 + part2 + part3 == "hello world"


@pytest.mark.asyncio
async def test_create_llm_passes_configured_languages(monkeypatch):
    from apps.providers.adapters.kenpath.service import create_llm

    monkeypatch.setattr(jwt, "encode", lambda *args, **kwargs: "signed-token")

    cfg = KenpathLLMConfig.model_validate(
        {
            "private_key": _TEST_PRIVATE_KEY,
            "jwt_sub": "+91-9000000000",
            "model": VISTAAR_DEV_MODEL,
            "source_lang": "bhb",
            "target_lang": "bhb",
        }
    )
    service = create_llm(cfg)
    assert isinstance(service, KenpathLLMService)
    assert service._source_lang == "bhb"
    assert service._target_lang == "bhb"
    assert service._use_voice_bhili is True
    assert service._voice_bhili_url == DEFAULT_VOICE_BHILI_DEV_URL
    assert service._is_prod is False

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": "ok there"}
    mock_response.text = ""

    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.get = AsyncMock(return_value=mock_response)
    service._client = mock_client

    chunks = [chunk async for chunk in service._iter_completions("test")]
    assert chunks == ["ok ", "there"]

    mock_client.get.assert_called_once()
    call_args = mock_client.get.call_args
    assert call_args.args[0] == DEFAULT_VOICE_BHILI_DEV_URL
    assert call_args.kwargs["follow_redirects"] is True
    params = call_args.kwargs["params"]
    assert params["source_lang"] == "bhb"
    assert params["target_lang"] == "bhb"
    assert "Authorization" not in call_args.kwargs["headers"]
    assert call_args.kwargs["headers"]["Accept"] == "application/json"


def test_create_llm_rejects_unsupported_language():
    from apps.providers.adapters.kenpath.service import create_llm

    cfg = KenpathLLMConfig.model_validate(
        {
            "private_key": _TEST_PRIVATE_KEY,
            "model": BHARAT_VISTAAR_PROD_MODEL,
            "source_lang": "mr",
            "target_lang": "mr",
        }
    )
    with pytest.raises(ValueError, match="not supported"):
        create_llm(cfg)


def test_create_llm_bharat_requires_bharat_private_key():
    from apps.providers.adapters.kenpath.service import create_llm

    cfg = KenpathLLMConfig.model_validate(
        {
            "private_key": _TEST_PRIVATE_KEY,
            "model": BHARAT_VISTAAR_PROD_MODEL,
            "source_lang": "hi",
        }
    )
    with pytest.raises(ValueError, match="bharat_prod_private_key"):
        create_llm(cfg)

    cfg_dev = KenpathLLMConfig.model_validate(
        {
            "private_key": _TEST_PRIVATE_KEY,
            "model": BHARAT_VISTAAR_DEV_MODEL,
            "source_lang": "hi",
        }
    )
    with pytest.raises(ValueError, match="bharat_dev_private_key"):
        create_llm(cfg_dev)


@pytest.mark.asyncio
async def test_create_llm_bharat_vistaar_streams_sse(monkeypatch):
    from apps.providers.adapters.kenpath.service import create_llm

    monkeypatch.setattr(jwt, "encode", lambda *args, **kwargs: "bharat-token")

    cfg = KenpathLLMConfig.model_validate(
        {
            "private_key": "vistaar-pem-unused",
            "bharat_dev_private_key": _TEST_PRIVATE_KEY,
            "model": BHARAT_VISTAAR_DEV_MODEL,
            "source_lang": "hi",
            "target_lang": "hi",
        }
    )
    service = create_llm(cfg)
    assert isinstance(service, BharatVistaarLLMService)
    assert service._private_key == _TEST_PRIVATE_KEY
    assert service._completions_path == BHARAT_VISTAAR_DEV_PATH
    assert service._base_url == DEFAULT_BHARAT_VISTAAR_DEV_URL

    service.set_call_id("call-sse-1")

    delta1 = json.dumps({"audio": "hello ", "end_interaction": False})
    delta2 = json.dumps({"audio": "hello world", "end_interaction": False})
    sse = (
        f'data: {{"choices":[{{"delta":{{"content":{json.dumps(delta1)}}}}}]}}\n'
        f'data: {{"choices":[{{"delta":{{"content":{json.dumps(delta2)}}}}}]}}\n'
        "data: [DONE]\n"
    ).encode("utf-8")

    stream_cm = AsyncMock()
    response = AsyncMock()
    response.status_code = 200

    async def aiter_bytes():
        yield sse

    response.aiter_bytes = aiter_bytes
    stream_cm.__aenter__.return_value = response
    stream_cm.__aexit__.return_value = None

    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.stream.return_value = stream_cm
    service._client = mock_client

    chunks = [
        chunk
        async for chunk in service._stream_chat(
            [{"role": "user", "content": "test"}],
        )
    ]
    assert chunks == ["hello ", "world"]

    mock_client.stream.assert_called_once()
    call_args = mock_client.stream.call_args
    assert call_args.args[0] == "POST"
    assert call_args.args[1] == f"{DEFAULT_BHARAT_VISTAAR_DEV_URL}{BHARAT_VISTAAR_DEV_PATH}"
    assert call_args.kwargs["follow_redirects"] is True
    headers = call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer bharat-token"
    assert headers["X-Language"] == "hi"
    assert headers["X-Session-ID"] == "call-sse-1"
    assert call_args.kwargs["json"]["model"] == BHARAT_VISTAAR_CHAT_MODEL
    assert call_args.kwargs["json"]["stream"] is True


@pytest.mark.asyncio
async def test_bharat_vistaar_non_200_raises(monkeypatch):
    monkeypatch.setattr(jwt, "encode", lambda *args, **kwargs: "bharat-token")
    service = BharatVistaarLLMService(
        private_key=_TEST_PRIVATE_KEY,
        base_url=DEFAULT_BHARAT_VISTAAR_PROD_URL,
        completions_path=BHARAT_VISTAAR_PROD_PATH,
        model=BHARAT_VISTAAR_PROD_MODEL,
        source_lang="en",
    )

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

    with pytest.raises(RuntimeError, match="Bharat Vistaar API Error 500"):
        async for _ in service._stream_chat([{"role": "user", "content": "hi"}]):
            pass


@pytest.mark.asyncio
async def test_voice_bhili_prod_sends_jwt(monkeypatch):
    monkeypatch.setattr(jwt, "encode", lambda *args, **kwargs: "signed-token")
    service = KenpathLLMService(
        private_key=_TEST_PRIVATE_KEY,
        jwt_sub="+91-9000000000",
        base_url="https://voice-prod.mahapocra.gov.in",
        voice_bhili_url=DEFAULT_VOICE_BHILI_PROD_URL,
        model=VISTAAR_PROD_MODEL,
        source_lang="bhb",
        target_lang="bhb",
    )
    assert service._is_prod is True

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": "ok"}
    mock_response.text = ""

    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.get = AsyncMock(return_value=mock_response)
    service._client = mock_client

    chunks = [chunk async for chunk in service._iter_voice_bhili_text("test")]
    assert chunks == ["ok"]
    headers = mock_client.get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer signed-token"
    assert mock_client.get.call_args.kwargs["follow_redirects"] is True


@pytest.mark.asyncio
async def test_voice_bhili_non_200_raises(monkeypatch):
    monkeypatch.setattr(jwt, "encode", lambda *args, **kwargs: "signed-token")
    service = KenpathLLMService(
        private_key=_TEST_PRIVATE_KEY,
        jwt_sub="+91-9000000000",
        base_url="https://vistaar-dev.mahapocra.gov.in",
        voice_bhili_url=DEFAULT_VOICE_BHILI_DEV_URL,
        model=VISTAAR_DEV_MODEL,
        source_lang="bhb",
        target_lang="bhb",
    )

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "server error"

    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.get = AsyncMock(return_value=mock_response)
    service._client = mock_client

    with pytest.raises(RuntimeError, match="Voice Bhili API Error 500"):
        async for _ in service._iter_voice_bhili_text("test"):
            pass


def test_response_requests_end_call():
    assert response_requests_end_call("goodbye") is True
    assert response_requests_end_call("Goodbye") is True
    assert response_requests_end_call("goodbye ") is True
    assert response_requests_end_call("bye bye") is False
    assert response_requests_end_call("see you later") is False
    assert response_requests_end_call("Hello, how can I help?") is False
    assert response_requests_end_call("") is False


def test_strip_goodbye_for_tts():
    assert strip_goodbye_for_tts("goodbye") == ""
    assert strip_goodbye_for_tts("goodbye ") == ""
    assert strip_goodbye_for_tts("Goodbye") == ""
    assert strip_goodbye_for_tts("hello world") == "hello world"
    assert strip_goodbye_for_tts("hello goodbye") == "hello"
    assert strip_goodbye_for_tts("hello goodbye ") == "hello "

@pytest.mark.asyncio
async def test_end_call_pushes_end_worker_frame(service: KenpathLLMService):
    pushed: list = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append((frame, direction))

    service.push_frame = capture  # type: ignore[method-assign]
    await end_call(service)
    assert len(pushed) == 1
    frame, direction = pushed[0]
    assert isinstance(frame, EndWorkerFrame)
    assert direction == FrameDirection.DOWNSTREAM


@pytest.mark.asyncio
async def test_vistaar_goodbye_pushes_end_worker_after_response(
    service: KenpathLLMService, monkeypatch
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
    assert any(isinstance(f, LLMFullResponseStartFrame) for f in pushed)
    assert any(isinstance(f, LLMFullResponseEndFrame) for f in pushed)
    end_idxs = [i for i, f in enumerate(pushed) if isinstance(f, LLMFullResponseEndFrame)]
    worker_idxs = [i for i, f in enumerate(pushed) if isinstance(f, EndWorkerFrame)]
    assert end_idxs and worker_idxs
    assert worker_idxs[0] > end_idxs[0]


@pytest.mark.asyncio
async def test_vistaar_no_goodbye_skips_end_worker(
    service: KenpathLLMService, monkeypatch
):
    monkeypatch.setattr(jwt, "encode", lambda *args, **kwargs: "signed-token")

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

    pushed: list = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    service.push_frame = capture  # type: ignore[method-assign]
    service._push_llm_text = AsyncMock()  # type: ignore[method-assign]
    service.start_processing_metrics = AsyncMock()  # type: ignore[method-assign]
    service.stop_processing_metrics = AsyncMock()  # type: ignore[method-assign]
    service.start_ttfb_metrics = AsyncMock()  # type: ignore[method-assign]
    service.stop_ttfb_metrics = AsyncMock()  # type: ignore[method-assign]

    context = LLMContext(messages=[{"role": "user", "content": "hi"}])
    await service.process_frame(LLMContextFrame(context=context), FrameDirection.DOWNSTREAM)

    assert any(isinstance(f, LLMFullResponseEndFrame) for f in pushed)
    assert not any(isinstance(f, EndWorkerFrame) for f in pushed)


@pytest.mark.asyncio
async def test_bharat_end_interaction_pushes_end_worker(monkeypatch):
    monkeypatch.setattr(jwt, "encode", lambda *args, **kwargs: "bharat-token")
    service = BharatVistaarLLMService(
        private_key=_TEST_PRIVATE_KEY,
        base_url=DEFAULT_BHARAT_VISTAAR_DEV_URL,
        completions_path=BHARAT_VISTAAR_DEV_PATH,
        model=BHARAT_VISTAAR_DEV_MODEL,
        source_lang="hi",
    )

    delta = json.dumps(
        {"audio": "namaste", "end_interaction": True, "language": "hi"}
    )
    sse = (
        f'data: {{"choices":[{{"delta":{{"content":{json.dumps(delta)}}}}}]}}\n'
        "data: [DONE]\n"
    ).encode("utf-8")

    stream_cm = AsyncMock()
    response = AsyncMock()
    response.status_code = 200

    async def aiter_bytes():
        yield sse

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

    end_idxs = [i for i, f in enumerate(pushed) if isinstance(f, LLMFullResponseEndFrame)]
    worker_idxs = [i for i, f in enumerate(pushed) if isinstance(f, EndWorkerFrame)]
    assert end_idxs and worker_idxs
    assert worker_idxs[0] > end_idxs[0]
