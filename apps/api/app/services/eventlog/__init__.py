"""Event log: org-scoped, append-only records of who did what.

Producers import only ``emit``, ``Actor``, ``Target``, ``request_context`` and
registered event types from this package.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from bson import ObjectId, json_util
from fastapi import Request

from app.auth import BOT_SERVICE_EMAIL
from app.services.eventlog import store
from app.services.eventlog.registry import REGISTRY, EventType

__all__ = ["Actor", "EventType", "Outcome", "Target", "emit", "request_context"]

logger = logging.getLogger("voicera.eventlog")

ENVELOPE_VERSION = 1
SOURCE = "api"
EVENT_LOOP_WARNING = "eventlog emit() called on the event loop thread"
# Bounds for request-supplied values (a path id, the User-Agent), so a caller
# cannot write arbitrarily large rows into a log retained for at least a year.
MAX_TARGET_ID_LENGTH = 256
MAX_CONTEXT_VALUE_LENGTH = 512

Outcome = Literal["success", "failure"]
_OUTCOMES = frozenset({"success", "failure"})


@dataclass(frozen=True)
class Actor:
    type: Literal["user", "service", "system"]
    id: str
    role: str | None = None

    @classmethod
    def from_user(cls, current_user: Mapping[str, Any]) -> Actor:
        """Map the ``get_current_user`` dict to an actor."""
        email = str(current_user["email"])
        return cls(
            type="service" if email == BOT_SERVICE_EMAIL else "user",
            id=email,
            role=current_user.get("role"),
        )


@dataclass(frozen=True)
class Target:
    type: str
    id: str


def request_context(request: Request) -> dict[str, str]:
    """Client IP and user agent of ``request``, omitting absent values."""
    context: dict[str, str] = {}
    if request.client and request.client.host:
        context["ip"] = request.client.host
    user_agent = request.headers.get("user-agent")
    if user_agent:
        context["user_agent"] = user_agent
    return context


def emit(
    event_type: EventType,
    *,
    org_id: str,
    actor: Actor,
    target: Target | None = None,
    outcome: Outcome = "success",
    data: Mapping[str, Any] | None = None,
    context: Mapping[str, str] | None = None,
) -> None:
    """Record one event. Never raises.

    Blocking: performs one insert bounded by ``EVENTLOG_WRITE_TIMEOUT_MS``.
    Call it from sync code or a worker thread, never directly on the event loop.
    """
    try:
        event = _build(event_type, org_id, actor, target, outcome, data, context)
    except Exception as exc:
        _fallback("build_failed", exc, None)
        return

    if _on_event_loop():
        logger.error(EVENT_LOOP_WARNING)

    try:
        store.insert(event)
    except Exception as exc:
        _fallback("write_failed", exc, event)


def _build(
    event_type: EventType,
    org_id: str,
    actor: Actor,
    target: Target | None,
    outcome: str,
    data: Mapping[str, Any] | None,
    context: Mapping[str, str] | None,
) -> dict[str, Any]:
    if REGISTRY.get(event_type.name) is not event_type:
        raise ValueError(f"unregistered event type: {event_type.name!r}")
    if not org_id:
        raise ValueError("org_id is required")
    if outcome not in _OUTCOMES:
        raise ValueError(f"invalid outcome: {outcome!r}")

    now = datetime.now(timezone.utc)
    event: dict[str, Any] = {
        "_id": ObjectId(),
        "v": ENVELOPE_VERSION,
        "org_id": org_id,
        "type": event_type.name,
        "ts": now.replace(microsecond=now.microsecond // 1000 * 1000),
        "source": SOURCE,
        "actor": asdict(actor),
        "outcome": outcome,
    }
    if target is not None:
        event["target"] = {"type": target.type, "id": target.id[:MAX_TARGET_ID_LENGTH]}
    if context:
        event["context"] = {
            key: str(value)[:MAX_CONTEXT_VALUE_LENGTH] for key, value in context.items()
        }
    if data:
        event["data"] = dict(data)
    return event


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _fallback(reason: str, exc: BaseException, event: dict[str, Any] | None) -> None:
    """Write the event to stdout as one Extended JSON line, re-insertable by ``_id``."""
    line: dict[str, Any] = {
        "eventlog_fallback": True,
        "reason": reason,
        "error": f"{type(exc).__name__}: {exc}",
    }
    if event is not None:
        line["event"] = event
    try:
        logger.error(json_util.dumps(line, json_options=json_util.RELAXED_JSON_OPTIONS))
    except Exception:
        logger.exception("eventlog fallback could not be serialised (%s)", reason)
