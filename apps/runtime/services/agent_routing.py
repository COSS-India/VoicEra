"""Agent category and telephony helpers for the voice runtime."""

from __future__ import annotations

from typing import Any, Literal

AgentCategory = Literal["telephony", "websocket"]


class AgentRoutingError(ValueError):
    """Raised when an agent cannot be routed to a runtime handler."""


def agent_category(agent: dict[str, Any]) -> AgentCategory:
    """Return the agent category, defaulting to websocket."""
    category = str(agent.get("agent_category") or "websocket").strip().lower()
    if category not in ("telephony", "websocket"):
        raise AgentRoutingError(f"Unsupported agent_category: {category!r}")
    return category  # type: ignore[return-value]


def telephony_provider(agent: dict[str, Any]) -> str:
    """Return the configured telephony provider for a telephony agent."""
    if agent_category(agent) != "telephony":
        raise AgentRoutingError("Agent is not a telephony agent")
    telephony = agent.get("telephony") or {}
    provider = str(telephony.get("provider") or "").strip().lower()
    if not provider:
        raise AgentRoutingError("Agent has no telephony provider configured")
    return provider
