"""UpdateSettings bridges for first-party STT/TTS adapters."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from pipecat.services.settings import STTSettings, TTSSettings

from apps.providers.runtime_language import (
    update_stt_settings_with_language,
    update_tts_settings_with_voice_language,
)


def _run(coro):
    return asyncio.run(coro)


async def _stt_super(delta: STTSettings) -> dict[str, Any]:
    return {"language": "hi"} if delta.language else {}


def test_stt_update_calls_set_language_from_delta():
    service = SimpleNamespace(
        _settings=SimpleNamespace(language="ml"),
        set_language=AsyncMock(),
    )

    changed = _run(
        update_stt_settings_with_language(
            service,
            STTSettings(language="ml"),
            super_update=_stt_super,
        )
    )

    assert changed == {"language": "hi"}
    service.set_language.assert_awaited_once_with("ml")


def test_stt_update_skips_set_language_when_language_omitted():
    service = SimpleNamespace(
        _settings=SimpleNamespace(language="hi"),
        set_language=AsyncMock(),
    )

    changed = _run(
        update_stt_settings_with_language(
            service,
            STTSettings(model="nova-3"),
            super_update=AsyncMock(return_value={"model": "old"}),
        )
    )

    assert changed == {"model": "old"}
    service.set_language.assert_not_awaited()


def test_stt_update_prefers_settings_language_after_super():
    service = SimpleNamespace(
        _settings=SimpleNamespace(language="kn"),
        set_language=AsyncMock(),
    )

    _run(
        update_stt_settings_with_language(
            service,
            STTSettings(language="ml"),
            super_update=AsyncMock(return_value={"language": "hi"}),
        )
    )

    service.set_language.assert_awaited_once_with("kn")


def test_tts_update_copies_voice_language_and_model():
    service = SimpleNamespace(_language="hi", _voice="Divya", _model="orpheus-indic")

    changed = _run(
        update_tts_settings_with_voice_language(
            service,
            TTSSettings(language="ml", voice="Anika", model="orpheus-v2"),
            super_update=AsyncMock(return_value={"voice": "Divya"}),
        )
    )

    assert changed == {"voice": "Divya"}
    assert service._language == "ml"
    assert service._voice == "Anika"
    assert service._model == "orpheus-v2"


def test_tts_update_leaves_private_attrs_when_fields_omitted():
    service = SimpleNamespace(_language="hi", _voice="Divya", _model="orpheus-indic")

    _run(
        update_tts_settings_with_voice_language(
            service,
            TTSSettings(),
            super_update=AsyncMock(return_value={}),
        )
    )

    assert service._language == "hi"
    assert service._voice == "Divya"
    assert service._model == "orpheus-indic"
