"""The higgs_tts provider, and its agreement with the model-server slot it calls.

The provider repeats two lists the server owns -- the voice roster
(voices/manifest.json) and the instructions vocabulary (tags.py) -- because the
voice pipeline cannot import model-server code at runtime. A repeated list
drifts, and here drift is a dropped sentence: a voice the server does not have
is a 400, and so is a style it does not know. Both live in this repository, so
the cross-check is cheap and runs without a GPU.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from apps.providers import Kind, ProviderType
from apps.providers.registry import TTS_CREATORS
from apps.providers.schema import provider_schemas

SLOT = Path(__file__).resolve().parents[3] / "model-server" / "tts" / "higgs-tts-3"


def _server_tags():
    spec = importlib.util.spec_from_file_location("higgs_slot_tags", SLOT / "tags.py")
    mod = importlib.util.module_from_spec(spec)
    # Registered before exec: @dataclass resolves field types through
    # sys.modules[cls.__module__], as test_rumik_codec.py notes.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _model_server_url(monkeypatch):
    monkeypatch.setenv("MODEL_SERVER_URL", "http://gateway:8100/v1")


def test_registered_as_a_local_tts_provider():
    pytest.importorskip("pipecat")
    from apps.providers.local.higgs_tts.catalog import TTS_VOICES
    from apps.providers.scoped_settings import CAPABILITIES_KEY

    schema = provider_schemas(Kind.TTS)["higgs_tts"]
    assert schema["provider_type"] == ProviderType.LOCAL
    assert schema["name"] == "Higgs TTS"
    assert schema["secrets"] == []
    assert "api_key" not in schema["fields"] and "base_url" not in schema["fields"]
    assert "higgs-tts-3" in schema["fields"]["model"]["examples"]

    codes = schema["fields"]["language"]["language_codes"]["higgs-tts-3"]
    assert set(codes) == {"hi", "bn", "ta", "te", "kn", "ml", "mr", "gu", "as", "ne",
                          "ur", "pa", "en"}
    # Not supported by the model: offering them would be nonsense audio.
    for absent in ("od", "sa", "brx", "doi", "kok", "ks", "mai", "mni", "sat", "sd"):
        assert absent not in codes

    settings = schema[CAPABILITIES_KEY]["higgs-tts-3"]["settings"]
    for canonical in codes:
        assert settings[canonical]["voice"]["options"] == list(TTS_VOICES)
        style = settings[canonical]["style"]
        assert style["default"] == "none"
        assert style["input_type"] == "dropdown"
        assert style["allow_custom_input"] is False
    assert settings["ta"]["voice"]["default"] == "Meera"
    assert settings["te"]["voice"]["default"] == "Arjun"
    assert settings["mr"]["voice"]["default"] == "Aditi"


def test_the_service_sends_tags_and_never_the_word_none():
    pytest.importorskip("pipecat")
    from apps.providers.local.higgs_tts.config import HiggsTTSConfig
    from apps.providers.local.higgs_tts.tts import HiggsTTSService

    svc = TTS_CREATORS["higgs_tts"](HiggsTTSConfig(language="hi", voice="Rahul"))
    assert isinstance(svc, HiggsTTSService)
    assert svc._init_sample_rate == 24000
    params = svc._request_params("नमस्ते")
    assert params == {"input": "नमस्ते", "model": "higgs-tts-3", "voice": "Rahul",
                      "response_format": "pcm"}

    tagged = TTS_CREATORS["higgs_tts"](
        HiggsTTSConfig(language="hi", voice="Aditi", style="emotion:contentment"))
    assert tagged._request_params("ठीक है")["instructions"] == "emotion:contentment"


def test_every_style_option_is_accepted_by_the_server():
    from apps.providers.local.higgs_tts.catalog import TTS_STYLES

    tags = _server_tags()
    for option in TTS_STYLES:
        tags.parse_instructions(option)   # raises TagError on anything unknown
    # ...and nothing the server offers is missing from the dropdown.
    assert set(TTS_STYLES) == {tags.NONE, *tags.instruction_options()}


def test_the_voice_roster_matches_the_server_manifest():
    from apps.providers.local.higgs_tts.catalog import (
        _NATIVE_VOICE,
        DEFAULT_TTS_VOICE,
        TTS_VOICES,
    )

    manifest = json.loads((SLOT / "voices" / "manifest.json").read_text(encoding="utf-8"))
    assert tuple(v["name"] for v in manifest["voices"]) == TTS_VOICES
    assert manifest["default"] == DEFAULT_TTS_VOICE
    recorded_in = {v["name"]: v["language"] for v in manifest["voices"]}
    for language, voice in _NATIVE_VOICE.items():
        assert recorded_in[voice] == language, f"{voice} is not the {language} recording"
