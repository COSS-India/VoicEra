"""JWT payload and signing for Mahavistaar ``/api/voice/`` (Vistaar dev/prod only)."""

from __future__ import annotations

import re
import time

import jwt

VISTAAR_JWT_ISS = "voice era"
VISTAAR_JWT_AUD = "mh-vistaar-voice"
VISTAAR_JWT_TTL_SECONDS = 3600

_INDIAN_E164 = re.compile(r"^\+91(\d{10})$")


def format_vistaar_jwt_sub(phone: str) -> str:
    """Kenpath expects ``+91-XXXXXXXXXX`` for Indian mobiles."""
    normalized = (phone or "").strip()
    match = _INDIAN_E164.match(normalized.replace("-", "").replace(" ", ""))
    if match:
        return f"+91-{match.group(1)}"
    if normalized.startswith("+91-") and len(normalized) >= 14:
        return normalized
    return normalized


def build_vistaar_payload(*, sub: str, now: int | None = None) -> dict[str, int | str]:
    issued = int(now if now is not None else time.time())
    return {
        "sub": format_vistaar_jwt_sub(sub),
        "iss": VISTAAR_JWT_ISS,
        "aud": VISTAAR_JWT_AUD,
        "iat": issued,
        "exp": issued + VISTAAR_JWT_TTL_SECONDS,
    }


def sign_vistaar_token(payload: dict[str, int | str], private_key: str) -> str:
    return jwt.encode(payload, private_key, algorithm="RS256")
