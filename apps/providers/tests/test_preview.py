"""Tests for the direct TTS preview registry and shared helpers."""

from __future__ import annotations

import wave
from io import BytesIO
from unittest.mock import patch

import httpx
import pytest
from pydantic import BaseModel

from apps.providers.preview import (
    PREVIEW_ADAPTERS,
    PreviewProviderError,
    has_preview_adapter,
    pcm_to_wav,
    register_preview,
    synthesize_preview,
)


class _DummyConfig(BaseModel):
    provider: str = "dummy"


def test_register_preview_adds_to_registry():
    # Arrange: patch.dict restores the shared registry even if the assert fails.
    with patch.dict(PREVIEW_ADAPTERS):
        # Act
        @register_preview("dummy-test-provider")
        async def synth(cfg, text, client):
            return b"audio"

        # Assert
        assert has_preview_adapter("dummy-test-provider")
    assert not has_preview_adapter("dummy-test-provider")


def test_synthesize_preview_dispatches_to_registered_adapter(monkeypatch):
    # Arrange
    async def fake_adapter(cfg, text, client):
        assert text == "hello"
        return b"wav-bytes"

    monkeypatch.setitem(PREVIEW_ADAPTERS, "dummy-test-provider", fake_adapter)

    async def run():
        async with httpx.AsyncClient() as client:
            return await synthesize_preview("dummy-test-provider", _DummyConfig(), "hello", client)

    # Act
    result = _run(run())

    # Assert
    assert result == b"wav-bytes"


def test_synthesize_preview_raises_for_unknown_provider():
    # Arrange
    async def run():
        async with httpx.AsyncClient() as client:
            await synthesize_preview("no-such-provider", _DummyConfig(), "hello", client)

    # Act / Assert
    with pytest.raises(PreviewProviderError, match="No preview adapter"):
        _run(run())


def test_pcm_to_wav_wraps_pcm_with_correct_header():
    # Arrange
    pcm = b"\x00\x01" * 8000  # 8000 frames of s16 mono

    # Act
    wav_bytes = pcm_to_wav(pcm, sample_rate=16000)

    # Assert
    with wave.open(BytesIO(wav_bytes), "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getnframes() == 8000


def _run(coro):
    import asyncio

    return asyncio.run(coro)
