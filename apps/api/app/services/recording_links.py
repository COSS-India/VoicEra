"""Expiring, signed public links to a call's recording.

Raya's post-call webhook carries ``call_recording_url``: a link the receiver
opens without logging in. Recordings live in MinIO, which is not reachable
from outside, so the link points at our API through the public URL and is
served only with a valid signature that has not expired:

    {PUBLIC_BASE_URL}/api/v1/calls/{call_id}/recording/signed?org=..&expires=..&sig=..

``sig`` is HMAC-SHA256 over ``"{org_id}.{call_id}.{expires}"`` with a key
derived from ``SECRET_KEY``. Rotating ``SECRET_KEY`` invalidates every link.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

from app.config import settings

_KEY_LABEL = b"voicera.recording-link.v1"


def _key() -> bytes:
    secret = (settings.SECRET_KEY or "").encode()
    if not secret:
        raise RuntimeError("SECRET_KEY is not set")
    return hmac.new(secret, _KEY_LABEL, hashlib.sha256).digest()


def _signature(org_id: str, call_id: str, expires: int) -> str:
    message = f"{org_id}.{call_id}.{expires}".encode()
    return hmac.new(_key(), message, hashlib.sha256).hexdigest()


def public_base_url() -> str | None:
    base = (settings.PUBLIC_BASE_URL or settings.FRONTEND_URL or "").strip().rstrip("/")
    return base or None


def signed_recording_url(org_id: str, call_id: str, *, now: float | None = None) -> str | None:
    """A link to the call's recording that works without login until it expires."""
    base = public_base_url()
    if not base:
        return None
    expires = int((now if now is not None else time.time()) + settings.RECORDING_LINK_TTL_SECONDS)
    query = urlencode({"org": org_id, "expires": expires, "sig": _signature(org_id, call_id, expires)})
    return f"{base}{settings.API_V1_PREFIX}/calls/{call_id}/recording/signed?{query}"


def verify(org_id: str, call_id: str, expires: int, sig: str, *, now: float | None = None) -> bool:
    if not org_id or not call_id or not sig:
        return False
    if (now if now is not None else time.time()) > expires:
        return False
    return hmac.compare_digest(_signature(org_id, call_id, expires), sig)
