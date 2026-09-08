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
