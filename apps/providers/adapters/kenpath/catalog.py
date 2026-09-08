"""Kenpath Vistaar / Bharat Vistaar LLM model catalog."""

from __future__ import annotations

from typing import Literal

DEFAULT_VISTAAR_PROD_URL = "https://voice-prod.mahapocra.gov.in"
DEFAULT_VISTAAR_DEV_URL = "https://vistaar-dev.mahapocra.gov.in"
DEFAULT_VOICE_BHILI_PROD_URL = "https://voice-prod.mahapocra.gov.in/api/voice-bhili/"
DEFAULT_VOICE_BHILI_DEV_URL = "https://vistaar-dev.mahapocra.gov.in/api/voice-bhili/"

DEFAULT_BHARAT_VISTAAR_PROD_URL = "https://chat-vistaar.da.gov.in"
DEFAULT_BHARAT_VISTAAR_DEV_URL = "https://dev-vistaar.da.gov.in"
BHARAT_VISTAAR_PROD_PATH = "/api/v1/chat/completions"
BHARAT_VISTAAR_DEV_PATH = "/api/v1/chat-dev/completions"
BHARAT_VISTAAR_CHAT_MODEL = "bharatvistaar-voice"
BHARAT_VISTAAR_JWT_ISS = "samvaad"

VISTAAR_PROD_MODEL = "vistaar-prod (Marathi, Bhili)"
VISTAAR_DEV_MODEL = "vistaar-dev (Marathi, Bhili)"
BHARAT_VISTAAR_PROD_MODEL = "bharatvistaar-prod (English, Hindi)"
BHARAT_VISTAAR_DEV_MODEL = "bharatvistaar-dev (Indic)"

LLM_MODELS: tuple[str, ...] = (
    VISTAAR_PROD_MODEL,
    VISTAAR_DEV_MODEL,
    BHARAT_VISTAAR_PROD_MODEL,
    BHARAT_VISTAAR_DEV_MODEL,
)
DEFAULT_LLM_MODEL = VISTAAR_PROD_MODEL

VISTAAR_LANGUAGES: tuple[str, ...] = ("mr", "bhb")
BHARAT_VISTAAR_PROD_LANGUAGES: tuple[str, ...] = ("en", "hi")
BHARAT_VISTAAR_DEV_LANGUAGES: tuple[str, ...] = (
    "en",
    "hi",
    "bn",
    "te",
    "mr",
    "ta",
    "gu",
    "kn",
    "ml",
    "as",
)
ALL_KENPATH_LANGUAGES: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            *VISTAAR_LANGUAGES,
            *BHARAT_VISTAAR_PROD_LANGUAGES,
            *BHARAT_VISTAAR_DEV_LANGUAGES,
        )
    )
)

KenpathBackend = Literal["vistaar", "bharatvistaar"]

MODEL_BASE_URLS: dict[str, str] = {
    VISTAAR_PROD_MODEL: DEFAULT_VISTAAR_PROD_URL,
    VISTAAR_DEV_MODEL: DEFAULT_VISTAAR_DEV_URL,
    BHARAT_VISTAAR_PROD_MODEL: DEFAULT_BHARAT_VISTAAR_PROD_URL,
    BHARAT_VISTAAR_DEV_MODEL: DEFAULT_BHARAT_VISTAAR_DEV_URL,
}

MODEL_VOICE_BHILI_URLS: dict[str, str] = {
    VISTAAR_PROD_MODEL: DEFAULT_VOICE_BHILI_PROD_URL,
    VISTAAR_DEV_MODEL: DEFAULT_VOICE_BHILI_DEV_URL,
}

MODEL_COMPLETIONS_PATHS: dict[str, str] = {
    BHARAT_VISTAAR_PROD_MODEL: BHARAT_VISTAAR_PROD_PATH,
    BHARAT_VISTAAR_DEV_MODEL: BHARAT_VISTAAR_DEV_PATH,
}

MODEL_LANGUAGES: dict[str, tuple[str, ...]] = {
    VISTAAR_PROD_MODEL: VISTAAR_LANGUAGES,
    VISTAAR_DEV_MODEL: VISTAAR_LANGUAGES,
    BHARAT_VISTAAR_PROD_MODEL: BHARAT_VISTAAR_PROD_LANGUAGES,
    BHARAT_VISTAAR_DEV_MODEL: BHARAT_VISTAAR_DEV_LANGUAGES,
}

MODEL_BACKENDS: dict[str, KenpathBackend] = {
    VISTAAR_PROD_MODEL: "vistaar",
    VISTAAR_DEV_MODEL: "vistaar",
    BHARAT_VISTAAR_PROD_MODEL: "bharatvistaar",
    BHARAT_VISTAAR_DEV_MODEL: "bharatvistaar",
}

# Config secret field used to sign JWTs for each model (see KenpathAuth).
# Matches mono: jwt_private_key.pem / prod_private_key_bh.pem / dev_private_key_bh.pem
VISTAAR_AUTH_SECRET = "private_key"
BHARAT_VISTAAR_PROD_AUTH_SECRET = "bharat_prod_private_key"
BHARAT_VISTAAR_DEV_AUTH_SECRET = "bharat_dev_private_key"

MODEL_AUTH_SECRETS: dict[str, str] = {
    VISTAAR_PROD_MODEL: VISTAAR_AUTH_SECRET,
    VISTAAR_DEV_MODEL: VISTAAR_AUTH_SECRET,
    BHARAT_VISTAAR_PROD_MODEL: BHARAT_VISTAAR_PROD_AUTH_SECRET,
    BHARAT_VISTAAR_DEV_MODEL: BHARAT_VISTAAR_DEV_AUTH_SECRET,
}


def resolve_base_url(model: str, override: str | None = None) -> str:
    if override:
        return override.rstrip("/")
    try:
        return MODEL_BASE_URLS[model].rstrip("/")
    except KeyError as exc:
        raise ValueError(f"Unknown Kenpath model: {model!r}") from exc


def resolve_backend(model: str) -> KenpathBackend:
    try:
        return MODEL_BACKENDS[model]
    except KeyError as exc:
        raise ValueError(f"Unknown Kenpath model: {model!r}") from exc


def resolve_completions_path(model: str) -> str:
    try:
        return MODEL_COMPLETIONS_PATHS[model]
    except KeyError as exc:
        raise ValueError(f"Kenpath model {model!r} has no Bharat completions path") from exc


def resolve_languages(model: str) -> tuple[str, ...]:
    try:
        return MODEL_LANGUAGES[model]
    except KeyError as exc:
        raise ValueError(f"Unknown Kenpath model: {model!r}") from exc


def resolve_auth_secret(model: str) -> str:
    """Return the KenpathAuth field name that signs JWTs for this model."""
    try:
        return MODEL_AUTH_SECRETS[model]
    except KeyError as exc:
        raise ValueError(f"Unknown Kenpath model: {model!r}") from exc
