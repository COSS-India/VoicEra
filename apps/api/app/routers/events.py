"""Event log (audit) read routes. Admin-only and scoped to the token's organisation."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pymongo.errors import PyMongoError

from app.auth import BOT_SERVICE_EMAIL, get_current_user
from app.config import settings
from app.database_init import ROLE_ADMIN, ROLE_SUPER_ADMIN
from app.services.eventlog import Actor, emit, request_context, store
from app.services.eventlog.registry import EVENTS_EXPORTED, REGISTRY
from app.services.eventlog.store import EventFilter
from app.models.schemas import EventListResponse, EventTypeResponse
from app.services import member_service

router = APIRouter(prefix="/events", tags=["events"])

DEFAULT_RANGE = timedelta(days=30)
MAX_RANGE = timedelta(days=366)
# Event ids are ObjectIds, whose timestamps start at the Unix epoch.
EARLIEST = datetime(1970, 1, 1, tzinfo=timezone.utc)
MAX_FILTER_LENGTH = 256
CSV_COLUMNS = (
    "id",
    "ts",
    "type",
    "outcome",
    "actor_type",
    "actor_id",
    "actor_role",
    "target_type",
    "target_id",
    "ip",
    "user_agent",
    "data",
)
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_CSV_FLUSH_ROWS = 500


def require_event_reader(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> str:
    """Return the caller's org_id if they are currently an admin of it.

    The role is re-read from Memberships because a JWT role can be stale. The
    bot service token carries ``role=admin`` but is always refused.
    """
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organisation in token",
        )
    email = current_user["email"]
    try:
        membership = (
            None
            if email == BOT_SERVICE_EMAIL
            else member_service.get_membership(email, org_id, strict=True)
        )
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not verify your role. Try again shortly.",
        ) from exc
    if not membership or membership.get("role") not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organisation admins can read the audit log",
        )
    return str(org_id)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def event_filter(
    types: list[str] | None = Query(None, alias="type", description="Repeatable"),
    actor_id: str | None = Query(None, max_length=MAX_FILTER_LENGTH),
    target_type: str | None = Query(None, max_length=MAX_FILTER_LENGTH),
    target_id: str | None = Query(None, max_length=MAX_FILTER_LENGTH),
    start: datetime | None = Query(
        None, alias="from", description="Inclusive; default 30 days before `to`"
    ),
    end: datetime | None = Query(
        None, alias="to", description="Inclusive; default now. Later values are treated as now"
    ),
    org_id: str = Depends(require_event_reader),
) -> EventFilter:
    now = datetime.now(timezone.utc)
    # No event is newer than now, and clamping keeps ObjectId bounds representable.
    end = min(_as_utc(end), now) if end else now
    start = _as_utc(start) if start else end - DEFAULT_RANGE
    if start < EARLIEST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`from` must not be before 1970-01-01",
        )
    if start > end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`from` must not be after `to`",
        )
    if end - start > MAX_RANGE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Time range must not exceed {MAX_RANGE.days} days",
        )
    unknown = sorted(set(types or ()) - REGISTRY.keys())
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown event type: {unknown[0][:MAX_FILTER_LENGTH]}",
        )
    return EventFilter(
        org_id=org_id,
        start=start,
        end=end,
        types=tuple(dict.fromkeys(types or ())),
        actor_id=actor_id or None,
        target_type=target_type or None,
        target_id=target_id or None,
    )


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _to_response(doc: dict[str, Any]) -> dict[str, Any]:
    event = {key: value for key, value in doc.items() if key != "_id"}
    event["id"] = str(doc["_id"])
    event["ts"] = _iso(doc["ts"])
    return event


@router.get("", response_model=EventListResponse)
def list_events(
    flt: EventFilter = Depends(event_filter),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, description="`next_cursor` of the previous page"),
) -> dict[str, Any]:
    """Events newest first, with keyset pagination."""
    if cursor is not None and not ObjectId.is_valid(cursor):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid cursor",
        )
    before = ObjectId(cursor) if cursor else None
    events = [_to_response(doc) for doc in store.iterate(flt, limit=limit, before=before)]
    return {
        "events": events,
        "next_cursor": events[-1]["id"] if len(events) == limit else None,
    }


@router.get("/types", response_model=list[EventTypeResponse])
def list_event_types(_: str = Depends(require_event_reader)) -> list[dict[str, str]]:
    """Registered event types."""
    return [{"name": t.name, "description": t.description} for t in REGISTRY.values()]


def _csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(_CSV_FORMULA_PREFIXES) else text


def _csv_row(doc: dict[str, Any]) -> list[str]:
    actor = doc.get("actor") or {}
    target = doc.get("target") or {}
    context = doc.get("context") or {}
    data = doc.get("data")
    values = (
        doc["_id"],
        _iso(doc["ts"]),
        doc.get("type"),
        doc.get("outcome"),
        actor.get("type"),
        actor.get("id"),
        actor.get("role"),
        target.get("type"),
        target.get("id"),
        context.get("ip"),
        context.get("user_agent"),
        json.dumps(data, default=str, separators=(",", ":")) if data else None,
    )
    return [_csv_cell(value) for value in values]


def _csv_lines(flt: EventFilter, max_rows: int) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def drain() -> str:
        text = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate()
        return text

    writer.writerow(CSV_COLUMNS)
    # Read one row past the cap, so the marker appears only when rows were cut.
    for written, doc in enumerate(store.iterate(flt, limit=max_rows + 1)):
        if written == max_rows:
            writer.writerow([f"# truncated: export is limited to {max_rows} rows"])
            break
        writer.writerow(_csv_row(doc))
        if (written + 1) % _CSV_FLUSH_ROWS == 0:
            yield drain()
    yield drain()


@router.get("/export")
def export_events(
    request: Request,
    flt: EventFilter = Depends(event_filter),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> StreamingResponse:
    """Stream matching events as CSV, newest first, capped at EVENTLOG_EXPORT_MAX_ROWS."""
    filters = {
        "from": _iso(flt.start),
        "to": _iso(flt.end),
        "types": list(flt.types),
        "actor_id": flt.actor_id,
        "target_type": flt.target_type,
        "target_id": flt.target_id,
    }
    emit(
        EVENTS_EXPORTED,
        org_id=flt.org_id,
        actor=Actor.from_user(current_user),
        context=request_context(request),
        data={"format": "csv", **{key: value for key, value in filters.items() if value}},
    )
    filename = f"audit-log-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.csv"
    return StreamingResponse(
        _csv_lines(flt, settings.EVENTLOG_EXPORT_MAX_ROWS),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
