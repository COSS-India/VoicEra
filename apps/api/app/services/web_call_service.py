"""Browser websocket call registration in CallLogs."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.services import agent_service, call_log_service
from app.services.agent_service import AgentNotFoundError

logger = logging.getLogger(__name__)


class WebCallError(Exception):
    """Raised when web call registration fails."""

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_websocket_agent(agent: dict[str, Any]) -> None:
    category = str(agent.get("agent_category") or "").strip().lower()
    if category != "websocket":
        raise WebCallError(
            "agent_id must reference a websocket agent",
            status_code=422,
        )


def register_web_call(
    org_id: str,
    agent_id: str,
    *,
    custom_variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a CallLog for a browser websocket session."""
    try:
        agent = agent_service.get_agent(org_id, agent_id)
    except AgentNotFoundError as exc:
        raise WebCallError(str(exc), status_code=404) from exc

    _require_websocket_agent(agent)

    variables = dict(custom_variables or {})
    call_id = str(uuid.uuid4())
    now = _now_iso()

    call_doc: dict[str, Any] = {
        "call_id": call_id,
        "provider_call_sid": f"web-{call_id}",
        "org_id": org_id,
        "agent_id": agent_id,
        "agent_name": agent.get("name"),
        "call_type": "web",
        "status": "in_progress",
        "call_response": "pending",
        "from_number": "browser",
        "to_number": "agent",
        "telephony_provider": None,
        "custom_variables": variables,
        "created_at": now,
        "updated_at": now,
        "start_time_utc": now,
        "end_time_utc": None,
        "duration": None,
        "recording_url": None,
        "transcript_url": None,
        "error_message": None,
    }
    created = call_log_service.create_call_log(call_doc)
    logger.info(
        "Web call registered call_id=%s org_id=%s agent_id=%s",
        call_id,
        org_id,
        agent_id,
    )
    return _to_register_response(created)


def _to_register_response(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "call_id": doc["call_id"],
        "status": doc.get("status", "in_progress"),
        "call_type": doc.get("call_type", "web"),
        "agent_id": doc.get("agent_id"),
        "custom_variables": doc.get("custom_variables") or {},
    }
