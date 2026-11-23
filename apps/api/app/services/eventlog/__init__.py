"""Event log: org-scoped, append-only records of who did what.

Producers import only ``emit``, ``emit_many``, ``Actor``, ``Resource`` (alias
``Target``), ``request_context`` and registered event types from this package.

An event is about one ``target`` and optionally some ``related`` resources, e.g.
a call (target) handled by an agent in a campaign (related). Every resource can
carry a ``name`` snapshot so the event stays readable after the resource is
renamed or deleted. ``resource_keys`` holds ``"type:id"`` for the target and each
related resource, so one index answers "everything about resource X" for any
resource type without a new field or index per type.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from bson import ObjectId, json_util
from fastapi import Request

from app.auth import BOT_SERVICE_EMAIL
from app.services.eventlog import store
from app.services.eventlog.registry import REGISTRY, RESOURCE_TYPES, EventType

__all__ = [
    "Actor",
    "EventType",
    "Outcome",
    "Resource",
    "Target",
    "emit",
    "emit_many",
    "request_context",
    "resource_key",
]

logger = logging.getLogger("voicera.eventlog")

ENVELOPE_VERSION = 1
SOURCE = "api"
EVENT_LOOP_WARNING = "eventlog emit() called on the event loop thread"
# Length caps for request-supplied values (path ids, names, User-Agent).
MAX_TARGET_ID_LENGTH = 256
MAX_RESOURCE_NAME_LENGTH = 256
MAX_CONTEXT_VALUE_LENGTH = 512
# Related resources per event; each one adds an index entry to the write.
MAX_RELATED = 8
# Events per insert_many() call in emit_many().
BATCH_SIZE = 100

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
class Resource:
    """Something an event is about. ``name`` is a snapshot at event time."""

    type: str
    id: str
    name: str | None = None


# The resource an event acts on.
Target = Resource


def resource_key(resource_type: str, resource_id: str) -> str:
    """Index key of a resource, as stored in ``resource_keys`` and used to filter."""
    return f"{resource_type}:{resource_id[:MAX_TARGET_ID_LENGTH]}"


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
    target: Resource | None = None,
    related: Sequence[Resource] = (),
    outcome: Outcome = "success",
    data: Mapping[str, Any] | None = None,
    context: Mapping[str, str] | None = None,
) -> None:
    """Record one event. Never raises.

    Blocking: performs one insert bounded by ``EVENTLOG_WRITE_TIMEOUT_MS``.
    Call it from sync code or a worker thread, never directly on the event loop.
    """
    try:
        event = _build(event_type, org_id, actor, target, related, outcome, data, context)
    except Exception as exc:
        _fallback("build_failed", exc, None)
        return

    if _on_event_loop():
        logger.error(EVENT_LOOP_WARNING)

    try:
        store.insert(event)
    except Exception as exc:
        _fallback("write_failed", exc, event)


def emit_many(
    event_type: EventType,
    *,
    org_id: str,
    actor: Actor,
    items: Iterable[tuple[Resource | None, Mapping[str, Any] | None]],
    related: Sequence[Resource] = (),
    outcome: Outcome = "success",
    context: Mapping[str, str] | None = None,
) -> None:
    """Record one action an actor took on many targets, e.g. a bulk export. Never raises.

    Each ``(target, data)`` item becomes one event sharing the other fields,
    including ``related``.
    Events are written in unordered batches of ``BATCH_SIZE``, one round trip
    per batch, each bounded by ``EVENTLOG_WRITE_TIMEOUT_MS``. Events that fail
    to build or write fall back to stdout one line each, exactly as ``emit()``.

    Blocking: call it from sync code or a worker thread, never on the event loop.
    """
    if _on_event_loop():
        logger.error(EVENT_LOOP_WARNING)

    batch: list[dict[str, Any]] = []
    for target, data in items:
        try:
            batch.append(
                _build(event_type, org_id, actor, target, related, outcome, data, context)
            )
        except Exception as exc:
            _fallback("build_failed", exc, None)
            continue
        if len(batch) == BATCH_SIZE:
            _write_batch(batch)
            batch = []
    if batch:
        _write_batch(batch)


def _write_batch(batch: list[dict[str, Any]]) -> None:
    try:
        store.insert_many(batch)
    except Exception as exc:
        # Part of the batch may have landed; a replay by ``_id`` is idempotent.
        for event in batch:
            _fallback("write_failed", exc, event)


def _resource(resource: Resource) -> dict[str, str]:
    if resource.type not in RESOURCE_TYPES:
        raise ValueError(f"unregistered resource type: {resource.type!r}")
    if not resource.id:
        raise ValueError(f"{resource.type} resource id is required")
    doc = {"type": resource.type, "id": str(resource.id)[:MAX_TARGET_ID_LENGTH]}
    if resource.name:
        doc["name"] = str(resource.name)[:MAX_RESOURCE_NAME_LENGTH]
    return doc


def _build(
    event_type: EventType,
    org_id: str,
    actor: Actor,
    target: Resource | None,
    related: Sequence[Resource],
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
    if len(related) > MAX_RELATED:
        raise ValueError(f"at most {MAX_RELATED} related resources, got {len(related)}")

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
    keys: list[str] = []
    if target is not None:
        event["target"] = _resource(target)
        keys.append(resource_key(event["target"]["type"], event["target"]["id"]))
    related_docs = []
    for resource in related:
        doc = _resource(resource)
        key = resource_key(doc["type"], doc["id"])
        if key not in keys:
            keys.append(key)
            related_docs.append(doc)
    if related_docs:
        event["related"] = related_docs
    if keys:
        event["resource_keys"] = keys
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
