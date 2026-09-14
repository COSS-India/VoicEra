"""Pipecat pipeline orchestration."""

from __future__ import annotations

from typing import Any

__all__ = ["run_telephony_bot", "run_websocket_bot"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from apps.runtime.services.pipecat import runners

        return getattr(runners, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
