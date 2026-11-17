"""tts/maya2-native: the slot contract on top of upstream's server.

The folder wraps `maya3.server` rather than rewriting it (see its server.py), so
what needs pinning here is the layer this repo adds -- and the failure modes are
the quiet kind:

* a missing `X-Audio-Format`, so the client guesses the width of what arrives;
* upstream's `wav` default, which puts a RIFF header in front of a PCM stream
  and plays as a click followed by noise;
* `od` reaching the model as an unknown language, which upstream answers with a
  400 -- every Odia agent fails, while Hindi keeps working and hides it;
* OpenAI's `alloy` becoming upstream's `plain`, a random speaker per request,
  which sounds like a different person every sentence and errors nowhere.

Two halves. contract.py and config.py import nothing third-party and always run.
The server half drives the real SlotServer over upstream's own CPU fake engine
(maya3/tests/fakes.py), so it needs the maya3 source importable -- no torch, no
GPU. Point PYTHONPATH at a checkout of the commit requirements.txt pins:

    git clone https://github.com/MayaResearch/maya2-native /tmp/maya3
    PYTHONPATH=/tmp/maya3 python -m pytest tests/test_maya2_native.py

Without it that half skips, and the contract half still runs.
"""

from __future__ import annotations

import contextlib
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "tts" / "maya2-native"


def _load(names: tuple[str, ...]) -> dict:
    """Load folder modules by path under their own names, then put sys.modules back.

    server.py does `import contract` and `from config import Config`, so those
    two must be importable by bare name while it loads -- and `config` is also
    the name of a file in other model folders, so nothing is left behind.
    """
    saved = {n: sys.modules.get(n) for n in names}
    loaded = {}
    try:
        for name in names:
            spec = importlib.util.spec_from_file_location(name, MODEL / f"{name}.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            loaded[name] = mod
    finally:
        for name, prev in saved.items():
            if prev is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prev
    return loaded


_mods = _load(("contract", "config"))
contract, config = _mods["contract"], _mods["config"]


# --------------------------------------------------------------------- contract


@pytest.mark.parametrize(
    ("given", "wire"),
    [
        ("od", "or"),
        ("or", "or"),
        ("OD", "or"),
        ("hi-IN", "hi"),
        ("en_IN", "en"),
        ("as", "as"),
        (" ta ", "ta"),
    ],
)
def test_languages_reach_the_model_by_its_own_codes(given, wire):
    assert contract.wire_language(given) == wire


@pytest.mark.parametrize("given", ["bho", "sd", "klingon", 7])
def test_an_unknown_language_is_left_for_upstream_to_refuse(given):
    """Upstream's 400 names the field and lists the twelve; guessing here would not."""
    assert contract.wire_language(given) == given


def test_the_default_format_is_pcm_not_upstreams_wav():
    body, _ = contract.shape_speech_body({"input": "x"}, "pcm")
    assert body["response_format"] == "pcm"
    body, _ = contract.shape_speech_body({"input": "x", "response_format": "WAV"}, "pcm")
    assert body["response_format"] == "wav"


def test_language_and_its_alias():
    body, _ = contract.shape_speech_body({"input": "x", "lang": "od"}, "pcm")
    assert body["language"] == "or" and "lang" not in body
    body, _ = contract.shape_speech_body({"input": "x", "language": "mr", "lang": "hi"}, "pcm")
    assert body["language"] == "mr" and "lang" not in body
    body, _ = contract.shape_speech_body({"input": "x"}, "pcm")
    assert "language" not in body, "absent must stay absent so upstream reads the script"


def test_openai_fields_the_model_cannot_honour_are_reported_not_refused():
    body, headers = contract.shape_speech_body(
        {"input": "x", "instructions": "cheerful", "speed": 1.25}, "pcm"
    )
    assert "instructions" not in body and "speed" not in body
    assert headers == {"X-Instructions-Ignored": "1", "X-Speed-Ignored": "1.25"}

    body, headers = contract.shape_speech_body(
        {"input": "x", "speed": 1.0, "instructions": " "}, "pcm"
    )
    assert "speed" not in body and headers == {}


def test_the_input_body_is_not_modified():
    original = {"input": "x", "lang": "od", "speed": 2}
    contract.shape_speech_body(original, "pcm")
    assert original == {"input": "x", "lang": "od", "speed": 2}


@pytest.mark.parametrize(
    ("requested", "expect"),
    [
        (None, "Ahana"),
        ("", "Ahana"),
        ("  ", "Ahana"),
        ("alloy", "Ahana"),
        ("NOVA", "Ahana"),
        ("Kayal", "Kayal"),
        ("nobody", "nobody"),
    ],
)
def test_voice_selection(requested, expect):
    assert contract.pick_voice(requested, "Ahana", ["plain", "Ahana", "Kayal"]) == expect


def test_a_registered_voice_named_like_an_openai_one_is_kept():
    assert contract.pick_voice("nova", "Ahana", ["plain", "Nova"]) == "nova"


def test_every_speech_format_has_a_header_value():
    for fmt in contract.SPEECH_FORMATS:
        assert contract.audio_format_header(fmt) == fmt
    assert contract.audio_format_header("aac") is None
    assert contract.audio_format_header(None) is None


def test_the_roster_hides_plain_and_carries_languages():
    rows = [
        ("plain", "plain", None),
        (
            "Ahana",
            "named",
            {
                "langs": ["hi", "en"],
                "gender": "female",
                "age_band": "young",
                "description": "Young female voice",
            },
        ),
        ("asha", "icl_spk", {}),
    ]
    roster = contract.voice_roster(rows, "Ahana")
    assert roster["object"] == "list" and roster["default"] == "Ahana"
    ids = [v["id"] for v in roster["data"]]
    assert ids == ["Ahana", "asha"]
    ahana = roster["data"][0]
    assert ahana == {
        "id": "Ahana",
        "languages": ["hi", "en"],
        "gender": "female",
        "age": "young",
        "description": "Young female voice",
    }
    assert roster["data"][1]["mode"] == "icl_spk"
    assert roster["data"][1]["languages"] == list(contract.LANGS)


def test_untrained_language_is_cross_lingual_not_unknown():
    assert contract.untrained_language({"langs": ["en", "ta"]}, "hi")
    assert not contract.untrained_language({"langs": ["en", "ta"]}, "ta")
    assert not contract.untrained_language({}, "hi"), "a voice with no list claims nothing"


def test_the_languages_match_the_catalogue():
    import yaml

    entry = next(
        e
        for e in yaml.safe_load((ROOT / "models.yaml").read_text())["tts"]
        if e["id"] == "maya2-native"
    )
    assert entry["languages"] == list(contract.LANGS)
    assert entry["sample_rate"] == 24000
    assert entry["audio_format"] == "pcm"


# ----------------------------------------------------------------------- config


def test_config_defaults_are_the_compose_defaults(monkeypatch):
    """Two copies of every default -- source and compose.extra.yml -- that must agree."""
    import yaml

    for key in list(__import__("os").environ):
        if key.startswith("MAYA_") or key == "PORT":
            monkeypatch.delenv(key, raising=False)
    sys.modules["contract"] = contract
    try:
        cfg = config.Config.from_env()
    finally:
        sys.modules.pop("contract", None)

    env = yaml.safe_load((MODEL / "compose.extra.yml").read_text())["services"]["tts"][
        "environment"
    ]
    defaults = {}
    for value in env.values():
        m = re.fullmatch(r"\$\{(\w+):-(.*)\}", str(value))
        if m:
            defaults[m.group(1)] = m.group(2)
    as_cfg = {
        "MAYA_MODEL_PATH": cfg.model_path,
        "MAYA_MIMI_DIR": cfg.mimi_dir,
        "MAYA_ECAPA_DIR": cfg.ecapa_dir,
        "MAYA_MODEL_NAME": cfg.model_name,
        "MAYA_DEVICE": cfg.device,
        "MAYA_MAX_SEATS": str(cfg.max_seats),
        "MAYA_CAPACITY": str(cfg.capacity),
        "MAYA_DEPTH_DTYPE": cfg.depth_dtype,
        "MAYA_MAX_PENDING": str(cfg.max_pending),
        "MAYA_QUEUE_DEADLINE_MS": f"{cfg.queue_deadline_ms:g}",
        "MAYA_HTTP_MAX_LAG_S": f"{cfg.http_max_lag_s:g}",
        "MAYA_DEFAULT_VOICE": cfg.default_voice,
        "MAYA_DEFAULT_FORMAT": cfg.default_format,
        "MAYA_NORMALISE": str(cfg.normalise).lower(),
        "MAYA_VOICE_CLONING": str(cfg.voice_cloning).lower(),
        "MAYA_HOST": cfg.host,
        "MAYA_LOG_LEVEL": cfg.log_level,
    }
    assert set(as_cfg) == set(defaults), "compose.extra.yml and config.py name different variables"
    for key, value in as_cfg.items():
        assert defaults[key] == value, (
            f"{key}: compose says {defaults[key]!r}, config.py says {value!r}"
        )
    assert cfg.model_name == MODEL.name, "the model name must equal the folder and catalogue id"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("MAYA_MAX_SEATS", "0"),
        ("MAYA_DEPTH_DTYPE", "int8"),
        ("MAYA_DEFAULT_FORMAT", "aac"),
        ("MAYA_NORMALISE", "maybe"),
        ("MAYA_CAPACITY", "lots"),
    ],
)
def test_a_bad_setting_names_its_variable(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    sys.modules["contract"] = contract
    try:
        with pytest.raises(ValueError, match=key):
            config.Config.from_env()
    finally:
        sys.modules.pop("contract", None)


# ----------------------------------------------------------------------- server


def _server_modules():
    pytest.importorskip("aiohttp")
    pytest.importorskip(
        "maya3.server", reason="maya3 source not on PYTHONPATH (see module docstring)"
    )
    fakes = pytest.importorskip("maya3.tests.fakes")
    return _load(("contract", "config", "server"))["server"], fakes


VOICES = {
    "Ahana": ["bn", "en", "gu", "hi", "kn", "ml", "mr", "or", "pa", "ta", "te"],
    "Kayal": ["en", "ta"],
}


@contextlib.asynccontextmanager
async def running(**cfg_kw):
    from aiohttp.test_utils import TestClient, TestServer

    server, fakes = _server_modules()
    tts = fakes.FakeTTS()
    for name, langs in VOICES.items():
        tts.engine.registry.add(fakes.named_voice(name, langs=langs, gender="female"))
    cfg = server.Config(normalise=False, **cfg_kw)
    srv = server.create_server(cfg, tts=tts)
    client = TestClient(TestServer(srv.app()))
    await client.start_server()
    try:
        yield client, tts
    finally:
        await client.close()
        tts.engine.close()


async def test_speech_defaults_to_pcm_and_says_so():
    async with running() as (client, tts):
        r = await client.post(
            "/v1/audio/speech", json={"input": "#frames=3 hello", "model": "maya2-native"}
        )
        assert r.status == 200, await r.text()
        body = await r.read()
        assert r.headers["X-Audio-Format"] == "pcm"
        assert r.headers["X-Sample-Rate"] == "24000"
        assert r.headers["Content-Type"].startswith("audio/pcm")
        assert r.headers["X-Model"] == "maya2-native"
        assert r.headers["X-Voice"] == "Ahana"
        assert len(body) == 3 * 1920 * 2, "three 80 ms frames of 16-bit mono, and no header"
        assert tts.engine.requests[-1].voice.id == "Ahana"


async def test_wav_is_available_and_labelled():
    async with running() as (client, _):
        r = await client.post(
            "/v1/audio/speech", json={"input": "#frames=2 hi", "response_format": "wav"}
        )
        assert r.status == 200
        assert r.headers["X-Audio-Format"] == "wav"
        assert (await r.read())[:4] == b"RIFF"


async def test_odia_reaches_the_model_as_or():
    async with running() as (client, tts):
        r = await client.post(
            "/v1/audio/speech", json={"input": "#frames=2 ନମସ୍କାର", "language": "od"}
        )
        assert r.status == 200, await r.text()
        await r.read()
        assert tts.engine.requests[-1].lang == "or"
        assert r.headers["X-Maya3-Language"] == "or"


async def test_openai_voice_names_get_the_default_voice_not_a_random_one():
    async with running() as (client, tts):
        r = await client.post("/v1/audio/speech", json={"input": "#frames=2 hi", "voice": "alloy"})
        assert r.status == 200
        await r.read()
        assert tts.engine.requests[-1].voice.id == "Ahana"


async def test_an_unknown_voice_is_an_openai_shaped_400():
    async with running() as (client, tts):
        r = await client.post("/v1/audio/speech", json={"input": "hi", "voice": "Nobody"})
        assert r.status == 400
        err = (await r.json())["error"]
        assert err["param"] == "voice" and "Kayal" in err["message"]
        assert "X-Audio-Format" not in r.headers
        assert not tts.engine.requests


async def test_ignored_fields_are_reported():
    async with running() as (client, _):
        r = await client.post(
            "/v1/audio/speech",
            json={"input": "#frames=2 hi", "instructions": "whisper", "speed": 1.5},
        )
        assert r.status == 200, await r.text()
        await r.read()
        assert r.headers["X-Instructions-Ignored"] == "1"
        assert r.headers["X-Speed-Ignored"] == "1.5"


async def test_a_voice_outside_its_languages_is_flagged():
    async with running() as (client, _):
        r = await client.post(
            "/v1/audio/speech", json={"input": "#frames=2 नमस्ते", "voice": "Kayal", "language": "hi"}
        )
        assert r.status == 200
        await r.read()
        assert r.headers["X-Voice-Untrained-Language"] == "hi"
        r = await client.post(
            "/v1/audio/speech",
            json={"input": "#frames=2 வணக்கம்", "voice": "Kayal", "language": "ta"},
        )
        await r.read()
        assert "X-Voice-Untrained-Language" not in r.headers


async def test_voices_models_and_demo():
    async with running() as (client, _):
        voices = await (await client.get("/v1/voices")).json()
        assert voices["default"] == "Ahana"
        assert [v["id"] for v in voices["data"]] == ["Ahana", "Kayal"]
        assert voices["data"][1]["languages"] == ["en", "ta"]

        models = await (await client.get("/v1/models")).json()
        assert [m["id"] for m in models["data"]] == ["maya2-native"]

        demo = await client.get("/demo")
        assert demo.status == 200 and "text/html" in demo.headers["Content-Type"]

        health = await client.get("/health")
        assert health.status == 200


async def test_voice_registration_is_off_by_default():
    async with running() as (client, tts):
        r = await client.post("/v1/voices", json={"voice_id": "x", "ref_text": "hi", "lang": "hi"})
        assert r.status == 403
        assert (await r.json())["error"]["code"] == "voice_cloning_disabled"
        r = await client.delete("/v1/voices/Ahana")
        assert r.status == 403
        assert "Ahana" in tts.engine.registry.ids()
