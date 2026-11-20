"""Maya 2 Native TTS, ported from main (apps/providers/local/maya2_native)."""

from __future__ import annotations

import pytest

from apps.providers import Kind, ProviderType
from apps.providers.registry import TTS_CREATORS
from apps.providers.schema import provider_schemas


def test_maya2_native_tts_registered(monkeypatch):
    pytest.importorskip("pipecat")
    from apps.providers.capabilities import model_ids
    from apps.providers.local.maya2_native.catalog import (
        SAMPLE_RATE,
        TTS_CAPABILITIES,
        TTS_VOICES,
        VOICE_LANGUAGES,
    )
    from apps.providers.local.maya2_native.config import Maya2NativeTTSConfig
    from apps.providers.local.maya2_native.tts import Maya2NativeTTSService
    from apps.providers.scoped_settings import CAPABILITIES_KEY

    monkeypatch.setenv("MODEL_SERVER_URL", "http://host.docker.internal:8100/v1")

    schema = provider_schemas(Kind.TTS)["maya2_native"]
    assert schema["provider_type"] == ProviderType.LOCAL
    assert schema["name"] == "Maya 2 Native"
    assert schema["secrets"] == []
    assert "api_key" not in schema["fields"]
    assert "base_url" not in schema["fields"]
    # No delivery conditioning in the model, so no field pretending otherwise.
    assert "style" not in schema["fields"]
    assert model_ids(TTS_CAPABILITIES)[0] in schema["fields"]["model"]["examples"]

    lang = schema["fields"]["language"]
    codes = lang["language_codes"]["maya2-native"]
    assert len(codes) == 12
    assert codes["od"] == "or"
    assert "en" in lang["examples"]

    settings = schema[CAPABILITIES_KEY]["maya2-native"]["settings"]
    assert len(TTS_VOICES) == 20
    # Only voices trained on a language are offered for it...
    assert settings["ta"]["voice"]["options"] == [
        v for v, langs in VOICE_LANGUAGES.items() if "ta" in langs
    ]
    assert "Kayal" in settings["ta"]["voice"]["options"]
    assert "Kayal" not in settings["hi"]["voice"]["options"]
    assert "Ishwari" not in settings["en"]["voice"]["options"]
    assert "Jahnavi" not in settings["pa"]["voice"]["options"]
    # ...and Assamese, which no voice was trained on, gets the eight broad ones.
    assert len(settings["as"]["voice"]["options"]) == 8
    for canonical in codes:
        assert settings[canonical]["voice"]["default"] == "Ahana"
        assert set(settings[canonical]) == {"voice"}

    svc = TTS_CREATORS["maya2_native"](Maya2NativeTTSConfig(language="od", voice="Ahana"))
    assert isinstance(svc, Maya2NativeTTSService)
    assert svc._voice == "Ahana"
    assert svc._style is None
    params = svc._request_params("ନମସ୍କାର")
    assert "instructions" not in params
    assert params["response_format"] == "pcm"
    # The script cannot tell Marathi from Hindi, so the language goes on the wire.
    assert params["extra_body"] == {"language": "or"}
    assert svc._init_sample_rate == SAMPLE_RATE == 24000

    marathi = TTS_CREATORS["maya2_native"](Maya2NativeTTSConfig(language="mr"))
    assert marathi._request_params("नमस्कार")["extra_body"] == {"language": "mr"}


def test_maya2_native_speaks_kannada(monkeypatch):
    pytest.importorskip("pipecat")
    from apps.providers.local.maya2_native.catalog import VOICE_LANGUAGES
    from apps.providers.local.maya2_native.config import Maya2NativeTTSConfig
    from apps.providers.scoped_settings import CAPABILITIES_KEY

    monkeypatch.setenv("MODEL_SERVER_URL", "http://host.docker.internal:8140/v1")
    settings = provider_schemas(Kind.TTS)["maya2_native"][CAPABILITIES_KEY]["maya2-native"]["settings"]
    kannada = settings["kn"]["voice"]["options"]
    assert kannada == [v for v, langs in VOICE_LANGUAGES.items() if "kn" in langs]
    assert "Jahnavi" in kannada
    svc = TTS_CREATORS["maya2_native"](Maya2NativeTTSConfig(language="kn", voice="Jahnavi"))
    assert svc._request_params("ನಮಸ್ಕಾರ")["extra_body"] == {"language": "kn"}
