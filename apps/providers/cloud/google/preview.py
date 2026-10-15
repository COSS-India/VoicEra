"""Direct (non-Pipecat) TTS preview for Google Cloud Text-to-Speech."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from functools import partial

import httpx
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from ...preview import (
    PREVIEW_SAMPLE_RATE_HZ,
    PreviewProviderError,
    post_for_audio,
    register_preview,
    resolve_wire_language,
)
from .catalog import TTS_CAPABILITIES, TTS_ENDPOINT, TTS_OAUTH_SCOPES, TTS_TOKEN_URI
from .config import GoogleTTSConfig

# One credentials object per service-account JSON (keyed by its hash, never
# the secret itself). google-auth keeps the ~1 h token on it and ``valid``
# turns false shortly before expiry, so a token is minted about once an hour.
# ponytail: unbounded, one entry per distinct key; fine at org scale.
_CREDENTIALS: dict[str, service_account.Credentials] = {}

# google-auth's token request defaults to a 120 s timeout. The refresh runs in a
# worker thread that the preview timeout cannot cancel, so bound each attempt
# here; google-auth retries only on 5xx, keeping the worst case near 3 attempts.
_TOKEN_REQUEST_TIMEOUT_S = 5.0
_TOKEN_REQUEST = partial(Request(), timeout=_TOKEN_REQUEST_TIMEOUT_S)


def _refresh_token(credentials_json: str) -> str:
    """Return a valid access token for the service account (blocking; run in a thread)."""
    cache_key = hashlib.sha256(credentials_json.encode()).hexdigest()
    creds = _CREDENTIALS.get(cache_key)
    if creds is None:
        # token_uri in the pasted JSON is user input, and google-auth POSTs to it
        # from this server: pin Google's endpoint so it can't be pointed inward.
        info = {**json.loads(credentials_json), "token_uri": TTS_TOKEN_URI}
        creds = service_account.Credentials.from_service_account_info(info, scopes=TTS_OAUTH_SCOPES)
        _CREDENTIALS[cache_key] = creds
    if not creds.valid:
        creds.refresh(_TOKEN_REQUEST)
    return creds.token


async def _access_token(cfg: GoogleTTSConfig) -> str:
    """Mint (or reuse) an OAuth token off the event loop; map any failure to PreviewProviderError."""
    # No ADC fallback: a preview must never bill the platform's own Google account.
    if not cfg.credentials:
        raise PreviewProviderError("Google preview needs service-account credentials")
    try:
        return await asyncio.to_thread(_refresh_token, cfg.credentials)
    except (ValueError, KeyError, TypeError, GoogleAuthError) as exc:
        raise PreviewProviderError(f"Google preview auth failed: {type(exc).__name__}") from exc


@register_preview("google")
async def synthesize(cfg: GoogleTTSConfig, text: str, client: httpx.AsyncClient) -> bytes:
    """Return WAV bytes for ``text``; raise :class:`PreviewProviderError` on any vendor failure."""
    payload = {
        # Plain text, not SSML: Chirp 3 HD voices reject SSML (pipecat does the same).
        "input": {"text": text},
        "voice": {"languageCode": resolve_wire_language(TTS_CAPABILITIES, cfg.model, cfg.language), "name": cfg.voice},
        # LINEAR16 from this endpoint already carries a WAV header.
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": PREVIEW_SAMPLE_RATE_HZ, "speakingRate": cfg.speed},
    }
    token = await _access_token(cfg)
    response = await post_for_audio(
        client, "Google", TTS_ENDPOINT, json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    try:
        audio = base64.b64decode(response.json()["audioContent"])
    except (ValueError, LookupError, TypeError) as exc:
        raise PreviewProviderError("Google preview returned a malformed response") from exc
    if not audio:
        raise PreviewProviderError("Google preview returned no audio")
    return audio
