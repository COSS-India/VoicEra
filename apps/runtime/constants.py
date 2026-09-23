"""Environment-derived configuration for the voice runtime."""

from __future__ import annotations

import os


def voice_server_ws_base() -> str:
    base = (os.getenv("VOICE_SERVER_BASE_URL") or "").strip().rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :]
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :]
    return base


def telephony_sample_rate() -> int:
    return int(os.getenv("SAMPLE_RATE", "8000"))


def websocket_sample_rate() -> int:
    return int(os.getenv("WEBSOCKET_SAMPLE_RATE", "16000"))


def rate_limit_enabled() -> bool:
    """Master switch shared with apps/api's Settings.RATE_LIMIT_ENABLED.

    Both services read the same root .env, so one value gates the whole
    rate-limiting work — including the runtime's duration guard, which would
    otherwise be the one layer that changes behaviour the moment it merges.
    """
    return (os.getenv("RATE_LIMIT_ENABLED", "false") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def max_call_duration_seconds() -> int:
    """Default single-call duration cap (env-configurable per deployment).

    Shares the env var name with apps/api's Settings.MAX_CALL_DURATION_SECONDS
    (see docs/developer/rate-limiting-plan.md) — both services read the same
    root .env, so one value configures both.
    """
    return int(os.getenv("MAX_CALL_DURATION_SECONDS", "600"))


def max_call_duration_ceiling_seconds() -> int:
    """Unconditional ceiling on call duration — see duration_guard.py."""
    return int(os.getenv("MAX_CALL_DURATION_CEILING_SECONDS", "1800"))
