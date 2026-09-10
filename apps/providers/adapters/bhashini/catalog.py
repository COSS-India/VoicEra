"""Bhashini STT and TTS model catalog."""

from __future__ import annotations

from typing import Literal

from ...capabilities import expand_settings

DEFAULT_WS_URL = "wss://dhruva-api.bhashini.gov.in/ws/v1/asr/stream"
DEFAULT_WS_SERVICE_ID = "bhashini/ai4b/indic-conformer/grpc"

DEFAULT_SOCKET_URL = "wss://dhruva-api.bhashini.gov.in"
DEFAULT_SOCKETIO_SERVICE_ID = "ai4bharat/whisper-medium-en--gpu--t4"

DEFAULT_GRPC_URL = "grpc.nvcf.nvidia.com:443"
DEFAULT_BHILI_MODEL = "asr_streaming"
DEFAULT_NEMOTRON_MODEL = "indic-nemotron-600m"
DEFAULT_TTS_VOICE = "Divya"

# Orpheus NVCF HTTP TTS (invocation domain + 202 status poll).
# Roster/styles match local Indic Orpheus (voices-v2.json).
DEFAULT_ORPHEUS_VOICE = "Amit"
DEFAULT_ORPHEUS_STYLE = "news"
ORPHEUS_SAMPLE_RATE = 24000
ORPHEUS_SPEECH_PATH = "/v1/audio/speech"
ORPHEUS_STATUS_BASE = "https://api.nvcf.nvidia.com/v2/nvcf/pexec/status/"
ORPHEUS_WIRE_MODEL = "orpheus"

_INDIC_LANGS = {
    "hi": "hi",
    "bn": "bn",
    "ta": "ta",
    "te": "te",
    "mr": "mr",
    "gu": "gu",
    "kn": "kn",
    "ml": "ml",
    "pa": "pa",
    "or": "od",
    "as": "as",
    "ur": "ur",
    "ne": "ne",
    "sa": "sa",
    "mni": "mni",
    "brx": "brx",
    "doi": "doi",
    "kok": "kok",
    "ks": "ks",
    "mai": "mai",
    "sat": "sat",
    "sd": "sd",
}

_EN_LANGS = {"en": "en"}
# NVCF/Triton wire code ``bhb`` → Voicera canonical ``bh`` (languages.py).
_BHILI_LANGS = {"bhb": "bh"}

# NVCF Nemotron Indic ASR (voicera.asr.v1 gRPC). Wire codes match local indic_nemotron.
# Odia is ``or`` on the wire / ``od`` in VoicEra; Bhili is ``bhb`` / ``bh``.
_NEMOTRON_LANGS: dict[str, str] = {
    "hi": "hi",
    "mr": "mr",
    "bn": "bn",
    "ta": "ta",
    "te": "te",
    "gu": "gu",
    "kn": "kn",
    "ml": "ml",
    "pa": "pa",
    "or": "od",
    "as": "as",
    "ur": "ur",
    "sa": "sa",
    "ne": "ne",
    "sd": "sd",
    "mai": "mai",
    "doi": "doi",
    "kok": "kok",
    "brx": "brx",
    "mni": "mni",
    "sat": "sat",
    "ks": "ks",
    "bho": "bho",
    "hne": "hne",
    "bgc": "bgc",
    "bhb": "bh",
    "en": "en",
}

# Vendor language code → speaker names for Indic Parler TTS.
TTS_SPEAKERS: dict[str, tuple[str, ...]] = {
    "as": ("Amit", "Sita", "Poonam", "Rakesh"),
    "bn": ("Arjun", "Aditi", "Tapan", "Rashmi", "Arnav", "Riya"),
    "brx": ("Bikram", "Maya", "Kalpana"),
    "hne": ("Bhanu", "Champa"),
    "doi": ("Karan",),
    "gu": ("Yash", "Neha"),
    "hi": ("Rohit", "Divya", "Aman", "Rani"),
    "kn": ("Suresh", "Anu", "Chetan", "Vidya"),
    "ml": ("Anjali", "Anju", "Harish"),
    "mni": ("Laishram", "Ranjit"),
    "mr": ("Sanjay", "Sunita", "Nikhil", "Radha", "Varun", "Isha"),
    # NVCF TTS wire ``bhli`` → canonical ``bh``; same speakers as Marathi.
    "bhli": ("Sanjay", "Sunita", "Nikhil", "Radha", "Varun", "Isha"),
    "ne": ("Amrita",),
    "or": ("Manas", "Debjani"),
    "pa": ("Divjot", "Gurpreet"),
    "sa": ("Aryan",),
    "ta": ("Kavitha", "Jaya"),
    "te": ("Prakash", "Lalitha", "Kiran"),
}

# TTS-only vendor→canonical remaps (not in Dhruva STT ``_INDIC_LANGS``).
_TTS_LANG_REMAP = {
    "bhli": "bh",
}

TTS_LANGS: dict[str, str] = {
    vendor: _TTS_LANG_REMAP.get(
        vendor,
        _INDIC_LANGS[vendor] if vendor in _INDIC_LANGS else vendor,
    )
    for vendor in TTS_SPEAKERS
}

TTS_DESCRIPTION_PRESETS: tuple[str, ...] = (
    "Slightly higher-pitched, expressive voice in a close-sounding environment. The voice is clear, with subtle emotional depth and a normal pace, captured in high-quality recording.",
    "Fast-paced speech with a slightly low-pitched voice, captured clearly in a close-sounding environment with excellent recording quality.",
    "Male voice speaking at a moderate pace with a slightly monotone tone. The recording is clear, with a close sound and only minimal ambient noise.",
    "High-pitched voice in a close environment. The voice is clear, with slight dynamic changes, and the recording is of excellent quality.",
    "High-pitched, engaging voice captured in a clear, close-sounding recording. A slightly slower delivery conveys a positive tone.",
    "High-pitched voice speaking at a slow pace. The voice is clear, with excellent recording quality and only moderate background noise.",
    "Slow speech with a high pitch and expressive tone. The recording is clear, showcasing an energetic and emotive voice.",
    "A young male speaker with a high-pitched American accent delivers speech at a slightly fast pace in a clear, close-sounding recording.",
    "High-pitched voice with a fast pace, conveying urgency. The recording is clear and intimate, with great emotional depth.",
    "High-pitched voice speaking at a normal pace in a clear, close-sounding environment. The neutral tone is captured with excellent audio quality.",
)

DEFAULT_TTS_DESCRIPTION = TTS_DESCRIPTION_PRESETS[0]

# Orpheus Indic: vendor language code → speakers (voices-v2.json roster).
# Speaker name uniquely implies language on the wire.
ORPHEUS_SPEAKERS: dict[str, tuple[str, ...]] = {
    "as": ("Prastuti", "Ankur"),
    "bn": ("Ishita", "Sourav"),
    "bhb": ("Bhima", "Dhulji", "Govind", "Jhamku", "Kanku", "Sarju", "Tantya"),
    "brx": ("Gwrbw", "Sansuma"),
    "doi": ("Preeti", "Sham"),
    "gu": ("Dhara", "Parth"),
    "hi": ("Kavya", "Amit"),
    "kn": ("Deepika", "Adarsh"),
    "ks": ("Zoon", "Ishfaq"),
    "kok": ("Anjali", "Sandeep"),
    "mai": ("Vaidehi", "Madhukar"),
    "ml": ("Lakshmi", "Kiran"),
    "mni": ("Thoibi", "Chaoba"),
    "mr": ("Anagha", "Chinmay"),
    "ne": ("Srijana", "Sagar"),
    "or": ("Itishree", "Akash"),
    "pa": ("Kaur", "Manpreet"),
    "sa": ("Bharati", "Aryaman"),
    "sat": ("Phulmani", "Sibu"),
    "sd": ("Moomal", "Rano"),
    "ta": ("Anitha", "Arun"),
    "te": ("Sravani", "Vamsi"),
    "ur": ("Saba", "Zaid"),
    "en": ("Kavya", "Amit"),
}

# Vendor language code → VoicEra canonical id (``or`` → ``od``, ``bhb`` → ``bh``).
ORPHEUS_LANGS: dict[str, str] = {
    "as": "as",
    "bn": "bn",
    "bhb": "bh",
    "brx": "brx",
    "doi": "doi",
    "gu": "gu",
    "hi": "hi",
    "kn": "kn",
    "ks": "ks",
    "kok": "kok",
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
    "en": "en",
}

ORPHEUS_STYLES: tuple[str, ...] = (
    "news",
    "AIR style news",
    "TV style news",
    "educational lecture",
    "single person narration audiobook",
    "children's stories",
    "advertisements",
    "Customer Care",
    "happy",
    "sad",
    "anger",
    "fear",
    "surprise",
    "disgust",
)

_STT_WS_MODEL = "bhashini/ai4bharat/conformer-multilingual-asr"
_STT_SOCKETIO_MODEL = DEFAULT_SOCKETIO_SERVICE_ID
_STT_BHILI_MODEL = DEFAULT_BHILI_MODEL
_STT_NEMOTRON_MODEL = DEFAULT_NEMOTRON_MODEL
_TTS_MODEL = "bhashini-indic-parler"
_ORPHEUS_MODEL = "orpheus"

STTBackend = Literal["websocket", "socketio", "bhili", "nemotron"]
TTSBackend = Literal["parler", "orpheus"]

STT_CAPABILITIES: dict[str, dict] = {
    _STT_WS_MODEL: {
        "languages": dict(_INDIC_LANGS),
        "settings": expand_settings(_INDIC_LANGS, {}),
    },
    _STT_SOCKETIO_MODEL: {
        "languages": dict(_EN_LANGS),
        "settings": expand_settings(_EN_LANGS, {}),
    },
    _STT_BHILI_MODEL: {
        "languages": dict(_BHILI_LANGS),
        "settings": expand_settings(_BHILI_LANGS, {}),
    },
    _STT_NEMOTRON_MODEL: {
        "languages": dict(_NEMOTRON_LANGS),
        "settings": expand_settings(_NEMOTRON_LANGS, {}),
    },
}


def _tts_description_meta() -> dict:
    return {
        "default": DEFAULT_TTS_DESCRIPTION,
        "options": list(TTS_DESCRIPTION_PRESETS),
        "input_type": "both",
        "allow_custom_input": True,
        "description": "Pick a preset voice description or write your own.",
    }


def _tts_settings() -> dict[str, dict]:
    settings: dict[str, dict] = {}
    for vendor, speakers in TTS_SPEAKERS.items():
        settings[vendor] = {
            "voice": {
                "default": speakers[0] if DEFAULT_TTS_VOICE not in speakers else DEFAULT_TTS_VOICE,
                "options": list(speakers),
                "input_type": "dropdown",
                "description": "Speaker name prepended to the voice description.",
            },
            "description": _tts_description_meta(),
        }
    return settings


def _orpheus_style_meta() -> dict:
    return {
        "default": DEFAULT_ORPHEUS_STYLE,
        "options": list(ORPHEUS_STYLES),
        "input_type": "dropdown",
        "description": "Speaking style from the Orpheus roster.",
    }


def _orpheus_settings() -> dict[str, dict]:
    settings: dict[str, dict] = {}
    for vendor, speakers in ORPHEUS_SPEAKERS.items():
        settings[vendor] = {
            "voice": {
                "default": (
                    speakers[0]
                    if DEFAULT_ORPHEUS_VOICE not in speakers
                    else DEFAULT_ORPHEUS_VOICE
                ),
                "options": list(speakers),
                "input_type": "dropdown",
                "description": "Speaker name; uniquely selects the language on Orpheus.",
            },
            "style": _orpheus_style_meta(),
        }
    return settings


TTS_CAPABILITIES: dict[str, dict] = {
    _TTS_MODEL: {
        "languages": dict(TTS_LANGS),
        "settings": _tts_settings(),
    },
    _ORPHEUS_MODEL: {
        "languages": dict(ORPHEUS_LANGS),
        "settings": _orpheus_settings(),
    },
}


def resolve_stt_backend(model: str) -> STTBackend:
    """Map catalog STT model id to transport backend."""
    if model == _STT_SOCKETIO_MODEL:
        return "socketio"
    if model == _STT_BHILI_MODEL:
        return "bhili"
    if model == _STT_NEMOTRON_MODEL:
        return "nemotron"
    if model in (_STT_WS_MODEL, DEFAULT_WS_SERVICE_ID):
        return "websocket"
    raise ValueError(f"Unknown Bhashini STT model: {model!r}")


def resolve_ws_service_id(model: str) -> str:
    """Map catalog model to Dhruva websocket serviceId."""
    if model == _STT_WS_MODEL:
        return DEFAULT_WS_SERVICE_ID
    if model == DEFAULT_WS_SERVICE_ID:
        return model
    raise ValueError(f"Unknown Bhashini WebSocket STT model: {model!r}")


def resolve_socketio_service_id(model: str) -> str:
    """Map catalog model to Dhruva Socket.IO serviceId."""
    if model == _STT_SOCKETIO_MODEL:
        return model
    raise ValueError(f"Unknown Bhashini Socket.IO STT model: {model!r}")


def resolve_bhili_model(model: str) -> str:
    """Map catalog model to NVCF Triton model name."""
    if model == _STT_BHILI_MODEL:
        return model
    raise ValueError(f"Unknown Bhashini Bhili STT model: {model!r}")


def resolve_tts_backend(model: str) -> TTSBackend:
    """Map catalog TTS model id to transport backend."""
    if model == _ORPHEUS_MODEL:
        return "orpheus"
    if model == _TTS_MODEL:
        return "parler"
    raise ValueError(f"Unknown Bhashini TTS model: {model!r}")


def resolve_ws_url(override: str | None = None) -> str:
    return (override or DEFAULT_WS_URL).rstrip("/")


def resolve_socket_url(override: str | None = None) -> str:
    return (override or DEFAULT_SOCKET_URL).rstrip("/")


def resolve_grpc_url(override: str | None = None) -> str:
    return (override or DEFAULT_GRPC_URL).strip()


def resolve_orpheus_base_url(function_id: str) -> str:
    """Per-function NVCF invocation base URL for Orpheus HTTP TTS."""
    fid = function_id.strip()
    if not fid:
        raise ValueError("Orpheus TTS requires a function id")
    return f"https://{fid}.invocation.api.nvcf.nvidia.com"


def resolve_wire_language(model: str, canonical: str) -> str:
    """Map canonical language id to vendor wire code for the given model."""
    for caps in (STT_CAPABILITIES, TTS_CAPABILITIES):
        entry = caps.get(model)
        if not entry:
            continue
        for vendor_code, canon in entry["languages"].items():
            if canon == canonical:
                return vendor_code
        break
    return canonical
