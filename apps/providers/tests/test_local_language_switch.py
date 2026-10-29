"""Mid-call language switching reaches the self-hosted providers correctly.

When two of an agent's languages share a provider and model, the runtime keeps
one service and sends it a settings delta (see
apps/runtime/services/language_switch/). That delta carries the agent config's
language as stored -- VoicEra's canonical id (``od``, ``bh``) -- and the voice
for the new language. These pin that each local provider applies it: STT
translates the language to its server's wire code, TTS picks up the new voice.
"""

from __future__ import annotations

import asyncio

import pytest
from pipecat.services.settings import STTSettings, TTSSettings

from apps.providers.registry import (
    STT_CREATORS,
    TTS_CONFIGS,
    TTS_CREATORS,
    load_providers,
)
from apps.providers.runtime_language import translate_delta_language


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _gateway_env(monkeypatch):
    monkeypatch.setenv("MODEL_SERVER_URL", "http://gateway:8100/v1")
    monkeypatch.setenv("MODEL_SERVER_WS_URL", "ws://gateway:8100/v1/asr/ws")
    monkeypatch.setenv("MODEL_SERVER_REALTIME_URL", "ws://gateway:8100/v1/realtime")
    load_providers()


def test_translate_delta_language_maps_and_skips_unset():
    to_wire = {"od": "or", "bh": "bhb"}.get

    delta = STTSettings(language="od")
    translate_delta_language(delta, lambda c: to_wire(c, c))
    assert delta.language == "or"

    delta = STTSettings(language="hi")
    translate_delta_language(delta, lambda c: to_wire(c, c))
    assert delta.language == "hi"

    untouched = STTSettings()
    translate_delta_language(untouched, lambda c: "x")
    assert not isinstance(untouched.language, str)


@pytest.mark.parametrize("provider", ["indic_conformer", "indic_transcribe"])
@pytest.mark.parametrize(("canonical", "wire"), [("od", "or"), ("bh", "bhb"), ("ta", "ta")])
def test_realtime_stt_switches_to_wire_code(provider, canonical, wire):
    from apps.providers.registry import STT_CONFIGS

    svc = STT_CREATORS[provider](STT_CONFIGS[provider](language="hi"))
    assert svc._wire_language == "hi"

    changed = _run(svc._update_settings(STTSettings(language=canonical)))

    assert "language" in changed
    assert str(svc._settings.language) == wire
    assert svc._wire_language == wire


@pytest.mark.parametrize(("canonical", "wire"), [("od", "or"), ("bh", "bhb"), ("bho", "bho")])
def test_nemotron_switches_to_wire_code(canonical, wire):
    from apps.providers.local.indic_nemotron.config import IndicNemotronSTTConfig

    svc = STT_CREATORS["indic_nemotron"](IndicNemotronSTTConfig(language="hi"))
    assert svc._language == "hi"

    _run(svc._update_settings(STTSettings(language=canonical)))

    assert svc._language == wire


@pytest.mark.parametrize(
    ("provider", "first", "second"),
    [
        ("indic_orpheus", {"language": "hi", "voice": "Amit"}, "Arun"),
        ("rumik_oss", {"language": "hi", "voice": "Ira"}, "Zoya"),
        ("indic_parler", {"language": "hi", "voice": "Divya"}, "Jaya"),
        ("indic_mio", {"language": "hi", "voice": "Aditi"}, "Meera"),
        ("higgs_tts", {"language": "hi", "voice": "Aditi"}, "Meera"),
    ],
)
def test_local_tts_switches_voice(provider, first, second):
    svc = TTS_CREATORS[provider](TTS_CONFIGS[provider](**first))
    assert svc._voice == first["voice"]

    _run(svc._update_settings(TTSSettings(voice=second, language="ta")))

    assert svc._voice == second
    assert svc._request_params("வணக்கம்")["voice"] == second
