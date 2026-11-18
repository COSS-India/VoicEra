"""Provider contract for post-call ``call_output``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


class CallOutputNotReady(Exception):
    """The data a provider needs is not there yet; try again later."""


@dataclass
class CallOutputResult:
    """What a provider worked out for one call."""

    output: dict[str, Any]
    # Raw facts behind ``output`` (phases, tool outcomes, …), stored for
    # debugging and audits; not sent in the webhook.
    signals: dict[str, Any] = field(default_factory=dict)


class CallOutputProvider(Protocol):
    name: str

    async def compute(
        self,
        call: dict[str, Any],
        agent: dict[str, Any],
        *,
        client: httpx.AsyncClient,
    ) -> CallOutputResult: ...


def get_provider(name: str | None) -> CallOutputProvider | None:
    """Look up a provider by name (lazy import keeps providers optional)."""
    if name == "bluedots":
        from app.services.call_output.bluedots.provider import BlueDotsCallOutputProvider

        return BlueDotsCallOutputProvider()
    return None


PROVIDER_NAMES = ("bluedots",)
