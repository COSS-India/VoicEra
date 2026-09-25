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
    import_vendor_previews,
    pcm_to_wav,
    register_preview,
    synthesize_preview,
)


class _DummyConfig(BaseModel):
    provider: str = "dummy"


def test_register_preview_adds_to_registry():
    # Arrange
    PREVIEW_ADAPTERS.pop("dummy-test-provider", None)

    # Act
    @register_preview("dummy-test-provider")
    async def synth(cfg, text, client):
        return b"audio"

    # Assert
    assert has_preview_adapter("dummy-test-provider")
    PREVIEW_ADAPTERS.pop("dummy-test-provider", None)


def test_synthesize_preview_dispatches_to_registered_adapter():
    # Arrange
    async def fake_adapter(cfg, text, client):
        assert text == "hello"
        return b"wav-bytes"

    PREVIEW_ADAPTERS["dummy-test-provider"] = fake_adapter

    async def run():
        async with httpx.AsyncClient() as client:
            return await synthesize_preview("dummy-test-provider", _DummyConfig(), "hello", client)

    # Act
    result = _run(run())

    # Assert
    assert result == b"wav-bytes"
    PREVIEW_ADAPTERS.pop("dummy-test-provider", None)


def test_synthesize_preview_raises_for_unknown_provider():
    async def run():
        async with httpx.AsyncClient() as client:
            await synthesize_preview("no-such-provider", _DummyConfig(), "hello", client)

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


def test_import_vendor_previews_registers_sarvam_without_raising():
    import_vendor_previews()
    assert has_preview_adapter("sarvam")


def test_import_vendor_previews_logs_and_continues_on_broken_vendor_module():
    # Arrange: the vendor package resolves, but its preview.py itself is broken
    # (e.g. a bad import inside it) — a ModuleNotFoundError whose .name is NOT
    # the "<vendor>.preview" module we asked for, unlike a vendor that simply
    # has no preview.py.
    import importlib as real_importlib

    real_import_module = real_importlib.import_module
    broken_error = ModuleNotFoundError("no module named 'not_a_real_dependency'")
    broken_error.name = "not_a_real_dependency"

    def fake_import(name, *args, **kwargs):
        if name == "apps.providers.cloud.sarvam.preview":
            raise broken_error
        return real_import_module(name, *args, **kwargs)

    with (
        patch("importlib.import_module", side_effect=fake_import),
        patch("apps.providers.preview.logger") as mock_logger,
    ):
        # Act
        import_vendor_previews()

    # Assert: the broken import was logged, not silently swallowed.
    assert mock_logger.warning.called
    assert "sarvam" in mock_logger.warning.call_args[0][0]


def _run(coro):
    import asyncio

    return asyncio.run(coro)
