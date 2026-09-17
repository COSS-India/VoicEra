"""VI runtime routing helpers."""

from __future__ import annotations

from typing import Any, Optional


def resolve_vi_agent_id(
    path_agent_id: Optional[str], start_info: dict[str, Any]
) -> Optional[str]:
    """Resolve agent id from URL path or VI custom parameters."""
    if path_agent_id:
        return path_agent_id

    custom_parameters = start_info.get("custom_parameters") or {}
    for key in ("agent_id", "agentId", "agent"):
        value = custom_parameters.get(key)
        if value:
            return str(value).strip()

    return None
