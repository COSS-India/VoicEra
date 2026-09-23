"""Raya (Bakbak) STT and TTS model catalog."""

from __future__ import annotations

from ...capabilities import expand_settings

DEFAULT_BASE_URL = "https://hub.getraya.app"
DEFAULT_STT_WS_URL = "wss://hub.getraya.app/transcribe"
# Display name shown in the UI; mapped to UUID via ``resolve_voice_id``.
DEFAULT_TTS_VOICE = "Neha"
DEFAULT_TTS_SAMPLE_RATE = 24000
STT_MODEL = "bakbak"

# Vendor language code → VoicEra canonical id.
# Odia is ``or`` on the wire / ``od`` in VoicEra.
_STT_LANGS: dict[str, str] = {
    "as": "as",
    "bn": "bn",
    "brx": "brx",
    "doi": "doi",
    "en": "en",
    "gu": "gu",
    "hi": "hi",
    "kn": "kn",
    "kok": "kok",
    "ks": "ks",
    "mai": "mai",
    "ml": "ml",
    "mni": "mni",
    "mr": "mr",
    "ne": "ne",
    "or": "od",
    "pa": "pa",
    "sa": "sa",
    "sat": "sat",
    "sd": "sd",
    "ta": "ta",
    "te": "te",
    "ur": "ur",
}

STT_CAPABILITIES: dict[str, dict] = {
    STT_MODEL: {
        "languages": dict(_STT_LANGS),
        "settings": expand_settings(_STT_LANGS, {}),
    },
}

# Voice id + display name from GET /v1/voices (hub.getraya.app), grouped by
# model then vendor language code. Voice IDs are model-specific.
# Note: `/v1/voices` currently lists dedicated m1 voices only for hi/kn/en;
# the TTS language enum still applies to both models (see OpenAPI TTSRequest).
TTS_VOICES: dict[str, dict[str, tuple[tuple[str, str], ...]]] = {
    "standard": {
        "as": (
            ("d4e5f6a7-b8c9-4a01-d345-e6f7a8b9c012", "Priti"),
            ("e5f6a7b8-c9d0-4b12-e456-f7a8b9c0d123", "Anjali"),
            ("f6a7b8c9-d0e1-4c23-f567-a8b9c0d1e234", "Ravi"),
        ),
        "bn": (
            ("145c9da5-96ef-4ad0-ba3b-2fafb3a63d87", "Ritu"),
            ("a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789", "Aishwarya"),
            ("b2c3d4e5-f6a7-4890-b123-c4d5e6f7a890", "Rajesh"),
            ("c3d4e5f6-a7b8-4901-c234-d5e6f7a8b901", "Riya"),
        ),
        "en-in": (
            ("0f24fb66-e495-4781-9e84-1224aa7dacde", "Nayra"),
            ("21e4f0f5-e2b3-40bc-9d9c-c6aecb87160a", "Mansi"),
            ("4fc34582-f0e0-418d-8d0b-2738637d9229", "Aanya"),
            ("bae3d3fe-64f9-4d2a-80b2-607ddff23528", "Roger"),
        ),
        "en-us": (
            ("6612acb5-988d-4d6e-8a71-5a719f41e2c8", "Sophia"),
            ("90534e23-8bcb-4b1c-a16b-b9a4be646321", "Solene"),
            ("97a155d0-8192-410e-a97c-540481182fc7", "Liam"),
            ("a98fc31c-7075-4ab9-af37-9abcd1ed186d", "Alice"),
            ("b8c716b3-dac1-4ec5-972d-9b5f872bd8a3", "Shelby"),
        ),
        "gu": (
            ("9a01bcde-2345-6789-abc1-123456abcdef", "Jignesh"),
            ("bcdef012-3456-789a-bcde-23456789abcd", "Megha"),
            ("fbc23456-789a-bcde-f012-456789abcdef", "Nirali"),
        ),
        "hi": (
            ("07308011-d790-4187-8ad9-afe7425627e9", "Neha"),
            ("5105f0fd-914c-4cfd-a338-c0fd55ae9eef", "Ananya"),
            ("5e3c580f-f42b-41ea-8c8a-c681c72f849d", "Arjun"),
            ("806b9f3e-cb5f-4bf1-aa78-7bdb9654079c", "Simran"),
            ("d6a002d0-230c-49b1-a137-b8a7d564b1ae", "Priyanka"),
            ("ea474fcd-69d1-4bb1-a740-8c33dd4f71f0", "Sakshi"),
        ),
        "kn": (
            ("522e4587-6611-4442-afdb-59f20ad5e420", "Rohan"),
            ("579335b8-add2-440e-b0bf-9c49d948fc25", "Divya"),
            ("5e1c0df9-1c49-4df8-bf4e-b4b61126dbc4", "Anjura Kn"),
            ("6a897d02-83ab-43ea-b17f-a8cc2d96a279", "Meera"),
            ("83966229-31f7-4883-90b0-09085940be61", "Manisha"),
            ("c7e386d6-02a3-41d0-9d9a-3d6199aaf702", "Abirami Kn"),
            ("da935a1b-5a61-4fdb-9807-e8eafdabe23c", "Drishti"),
        ),
        "ml": (
            ("42710cb4-fad8-48b9-b89c-960824b485f8", "Abirami ml"),
            ("57a1e849-8e0f-43ee-adab-b4b74a9d79e1", "Devika"),
            ("73597ca6-6357-4042-9380-498c7e758ae7", "Nikhil"),
            ("f9fa526d-5043-4dc8-9367-38428ebd0efb", "Nandana"),
        ),
        "mr": (
            ("0c48e416-d0d8-4518-a778-384172c987fe", "Kavya"),
            ("a8bb558d-8b9e-4941-9800-2308cf2d42f5", "Anika"),
            ("bd1a2614-9268-429c-98a4-727a034185c1", "Priya"),
            ("c849b31b-b0ba-488f-b97d-3fd12f2656f4", "Sneha"),
            ("daf27132-15fd-481b-ae26-aeba8d256901", "Monika"),
        ),
        "ne": (
            ("06043cea-c39e-4ecc-a9c3-3049ed71b370", "Dipesh"),
            ("5d6c7ee4-2563-4dab-9c8a-c3269e22cba9", "Ritu"),
            ("a5b9b67f-0654-41dc-ba95-0ef6c6ee9e17", "Karuna"),
        ),
        "ta": (
            ("ab17f0d3-3202-4344-8d6c-98c1bea5e518", "Vignesh"),
            ("b96afcac-e1b3-4081-9d40-40e9ff015534", "Anjura Ta"),
            ("e23a699d-581d-4f36-b15e-2755f1afaecc", "Parvathi"),
            ("fed6231c-7e35-4fbe-bbca-254f566e5dd5", "Abirami"),
        ),
        "te": (
            ("18897ed3-e3a8-46e0-ad0e-a176bcb6ceee", "Karthik"),
            ("25a7c7d9-57b3-488a-a880-33edf6642902", "Tanvi"),
            ("43bebf06-bf02-4b39-8358-e7469bda0c0e", "Abirami Te"),
            ("e39f7165-85e0-4bd8-b853-cb89c7dbd1b7", "Divya"),
            ("edf1b4a5-479c-4d85-885c-54c21a21beb5", "Anjura Te"),
        ),
    },
    "m1": {
        # API tags English m1 voices as ``en``; wire language is still en-in/en-us.
        "en": (
            ("7e04362e-096f-47ad-a3b3-3a2efcbe62bc", "Alice M1"),
            ("eaa0ec8c-e747-433a-8bf7-5f5e360ad932", "Ayushi"),
        ),
        "hi": (
            ("009ae8b5-4a03-492d-af1c-3055989ac734", "Anika M1"),
            ("029d327b-987b-4879-8375-454cba8424ec", "Raj M1"),
            ("27ecee77-5bba-4894-9800-5be26c78837d", "Dhruvi M1"),
            ("3fe4afbc-3bde-4c97-ab8e-37e3fb8c7ba2", "Anjura M1"),
            ("4220e163-90d3-4fde-8faa-0e464283dc2a", "Riya M1"),
            ("82e802d6-d90e-4065-a1cd-a74113fb52d1", "Shreya M1"),
            ("9c291ec7-81ce-4125-b206-80dbaacc858a", "Rahul M1"),
            ("d14c3aa6-4f90-4c11-be8f-2633a8c183b4", "Priya M1"),
            ("e38b1e16-9aee-4ab4-8a7e-2e7f7e51bb08", "Chaya M1"),
        ),
        "kn": (
            ("0ffd8c73-7c39-4b22-92f4-ebf33a6fae2c", "Kavya M1"),
        ),
    },
}

# TTSRequest.language enum — same for ``standard`` and ``m1``
# (https://docs.litwizlabs.com/api-reference/text-to-speech/text-to-speech-stream).
_TTS_LANGS: dict[str, str] = {
    "hi": "hi",
    "mr": "mr",
    "te": "te",
    "kn": "kn",
    "bn": "bn",
    "as": "as",
    "gu": "gu",
    "ne": "ne",
    "ml": "ml",
    "ta": "ta",
    "en-in": "en",
    "en-us": "en-US",
}

_TTS_SPEED = {
    "default": 1.0,
    "minimum": 0.5,
    "maximum": 1.5,
    "input_type": "slider",
}

_TTS_SAMPLE_RATE = {
    "default": DEFAULT_TTS_SAMPLE_RATE,
    "options": [8000, 16000, 22050, 24000],
    "input_type": "dropdown",
}

_DEFAULT_M1_VOICE = "Anjura M1"


def _all_model_voices(model: str) -> tuple[tuple[str, str], ...]:
    seen: dict[str, str] = {}
    for voices in TTS_VOICES[model].values():
        for voice_id, name in voices:
            seen.setdefault(voice_id, name)
    return tuple(seen.items())


def _voices_for_language(model: str, vendor: str) -> tuple[tuple[str, str], ...]:
    """Return voice options for a model+language.

    Prefer language-tagged voices from ``/v1/voices``. m1 English voices are
    tagged ``en`` but the wire language is ``en-in`` / ``en-us``. Languages
    without a dedicated m1 roster fall back to the full m1 voice set (docs:
    both models share the same language enum).
    """
    by_lang = TTS_VOICES[model]
    if vendor in by_lang:
        return by_lang[vendor]
    if model == "m1" and vendor in ("en-in", "en-us") and "en" in by_lang:
        return by_lang["en"]
    if model == "m1":
        return _all_model_voices("m1")
    return ()


def _tts_settings(model: str) -> dict[str, dict]:
    """Build per-language settings; voice ``options`` are display names for the UI."""
    settings: dict[str, dict] = {}
    for vendor in _TTS_LANGS:
        voices = _voices_for_language(model, vendor)
        if not voices:
            continue
        names = [name for _voice_id, name in voices]
        default = names[0]
        if model == "standard" and DEFAULT_TTS_VOICE in names:
            default = DEFAULT_TTS_VOICE
        elif model == "m1" and _DEFAULT_M1_VOICE in names:
            default = _DEFAULT_M1_VOICE
        settings[vendor] = {
            "voice": {
                "default": default,
                "options": names,
                "input_type": "dropdown",
                "allow_custom_input": True,
                "description": "Raya voice (mapped to voice_id on the wire).",
            },
            "speed": dict(_TTS_SPEED),
            "sample_rate": dict(_TTS_SAMPLE_RATE),
        }
    return settings


TTS_CAPABILITIES: dict[str, dict] = {
    "standard": {
        "languages": dict(_TTS_LANGS),
        "settings": _tts_settings("standard"),
    },
    "m1": {
        "languages": dict(_TTS_LANGS),
        "settings": _tts_settings("m1"),
    },
}


def resolve_wire_language(model: str, canonical: str, *, kind: str = "stt") -> str:
    """Map canonical language id to Raya wire code for the given model."""
    caps = STT_CAPABILITIES if kind == "stt" else TTS_CAPABILITIES
    entry = caps.get(model)
    if not entry:
        return canonical
    for vendor_code, canon in entry["languages"].items():
        if canon == canonical:
            return vendor_code
    return canonical


def resolve_voice_id(model: str, language: str, voice: str) -> str:
    """Map UI voice name (or raw UUID) to Raya ``voice_id`` for the API.

    ``language`` is the Raya wire code (e.g. ``hi``, ``en-in``).
    """
    value = (voice or "").strip()
    if not value:
        return value

    candidates = list(_voices_for_language(model, language))
    if not candidates:
        candidates = list(_all_model_voices(model))

    for voice_id, name in candidates:
        if value == voice_id or value == name:
            return voice_id

    # Fall back to any voice on this model (e.g. name from another language).
    for voice_id, name in _all_model_voices(model):
        if value == voice_id or value == name:
            return voice_id

    return value


def resolve_stt_ws_url() -> str:
    """Hardcoded STT WebSocket URL (not exposed on config / frontend)."""
    return DEFAULT_STT_WS_URL


def resolve_tts_base_url(override: str | None = None) -> str:
    return (override or DEFAULT_BASE_URL).rstrip("/")
