"""Tests for the Amul voice LLM adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.providers.adapters.amul.catalog import (
    DEFAULT_SOURCE_LANG,
    DEFAULT_URL,
    DEFAULT_USER_ID,
    VOICE_PATH,
    resolve_base_url,
)
from apps.providers.adapters.amul.config import AmulLLMConfig
from apps.providers.adapters.amul.llm import AmulLLMService, extract_last_user_message


def test_resolve_base_url_default_and_override():
    assert resolve_base_url(None) == DEFAULT_URL
    assert resolve_base_url("https://dev.amulai.in/") == "https://dev.amulai.in"


def test_extract_last_user_message_joins_trailing_users():
    context = MagicMock()
    context.get_messages.return_value = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "how many"},
        {"role": "user", "content": "animals"},
    ]
    assert extract_last_user_message(context) == "how many animals"


def test_create_llm_requires_token():
    from apps.providers.adapters.amul.service import create_llm

    missing = AmulLLMConfig.model_validate({})
    with pytest.raises(ValueError, match="bearer_token"):
        create_llm(missing)


def test_create_llm_uses_fixed_eval_defaults():
    from apps.providers.adapters.amul.llm import AmulLLMService
    from apps.providers.adapters.amul.service import create_llm

    service = create_llm(AmulLLMConfig.model_validate({"bearer_token": "eval-token"}))
    assert isinstance(service, AmulLLMService)
    assert service._base_url == DEFAULT_URL
    assert service._source_lang == DEFAULT_SOURCE_LANG == "gu"
    assert service._user_id == DEFAULT_USER_ID


@pytest.mark.asyncio
async def test_stream_voice_sends_bearer_and_reuses_call_id():
    service = AmulLLMService(
        bearer_token="eval-token",
        base_url=DEFAULT_URL,
        model="amul-dev (English, Gujarati)",
        source_lang="gu",
        user_id=DEFAULT_USER_ID,
    )
    service.set_call_id("eval-gu-1")

    stream_cm = AsyncMock()
    response = AsyncMock()
    response.status_code = 200

    async def aiter_bytes():
        text = "ભાવેશ પટેલ"
        raw = text.encode("utf-8")
        yield raw[:4]
        yield raw[4:]

    response.aiter_bytes = aiter_bytes
    stream_cm.__aenter__.return_value = response
    stream_cm.__aexit__.return_value = None

    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.stream.return_value = stream_cm
    service._client = mock_client

    chunks = [chunk async for chunk in service._stream_voice("મારી પાસે કેટલા પશુ છે?")]
    assert "".join(chunks) == "ભાવેશ પટેલ"

    mock_client.stream.assert_called_once()
    call = mock_client.stream.call_args
    assert call.args == ("GET", f"{DEFAULT_URL}{VOICE_PATH}")
    assert call.kwargs["follow_redirects"] is True
    assert call.kwargs["headers"]["Authorization"] == "Bearer eval-token"
    params = call.kwargs["params"]
    assert params["query"] == "મારી પાસે કેટલા પશુ છે?"
    assert params["session_id"] == "eval-gu-1"
    assert params["source_lang"] == "gu"
    assert params["target_lang"] == "gu"
    assert params["user_id"] == DEFAULT_USER_ID


@pytest.mark.asyncio
async def test_stream_voice_non_200_raises():
    service = AmulLLMService(
        bearer_token="eval-token",
        base_url=DEFAULT_URL,
        model="amul-dev (English, Gujarati)",
        source_lang="en",
    )
    stream_cm = AsyncMock()
    response = AsyncMock()
    response.status_code = 401
    response.aread = AsyncMock(return_value=b"unauthorized")
    stream_cm.__aenter__.return_value = response
    stream_cm.__aexit__.return_value = None

    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.stream.return_value = stream_cm
    service._client = mock_client

    with pytest.raises(RuntimeError, match="Amul API Error 401"):
        async for _ in service._stream_voice("How many animals do I have?"):
            pass
