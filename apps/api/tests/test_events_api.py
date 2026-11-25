"""/events routes: access control, filters, paging contract and CSV export."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pytest
from app.auth import BOT_SERVICE_EMAIL, get_current_user
from app.config import settings
from app.services.eventlog import store
from app.services.eventlog.registry import REGISTRY
from app.services.eventlog.store import EventFilter
from app.routers import events as events_router
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

ADMIN = {"email": "admin@example.com", "org_id": "org-1", "role": "admin"}


def _client(user: dict[str, Any] = ADMIN) -> TestClient:
    app = FastAPI()
    app.include_router(events_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _event(i: int = 0, **overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "_id": ObjectId(),
        "v": 1,
        "org_id": "org-1",
        "type": "call.transcript.viewed",
        "ts": datetime(2026, 11, 20, 9, 41, 12, 381000, tzinfo=timezone.utc) + timedelta(seconds=i),
        "source": "api",
        "actor": {"type": "user", "id": "jane@example.com", "role": "admin"},
        "target": {"type": "call", "id": f"call-{i}"},
        "outcome": "success",
        "context": {"ip": "203.0.113.7"},
        "data": {"object_key": "k"},
    }
    doc.update(overrides)
    return doc


@pytest.fixture
def membership_role() -> dict[str, str | None]:
    role: dict[str, str | None] = {"value": "admin"}

    def get_membership(email: str, org_id: str, **_: Any) -> dict[str, Any] | None:
        return {"email": email, "org_id": org_id, "role": role["value"]} if role["value"] else None

    with patch.object(events_router.member_service, "get_membership", side_effect=get_membership):
        yield role


@dataclass
class FakeStore:
    """Docs that ``store.iterate`` yields, and the arguments of each read."""

    docs: list[dict[str, Any]] = field(default_factory=list)
    reads: list[dict[str, Any]] = field(default_factory=list)

    def iterate(self, flt: EventFilter, *, limit: int, before: ObjectId | None = None):
        self.reads.append({"filter": flt, "limit": limit, "before": before})
        yield from self.docs[:limit]


@pytest.fixture
def fake_store() -> FakeStore:
    fake = FakeStore()
    with patch.object(store, "iterate", side_effect=fake.iterate):
        yield fake


@pytest.fixture
def emitted() -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    with patch.object(store, "insert", side_effect=captured.append):
        yield captured


# --- access control ---------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/v1/events", "/api/v1/events/types", "/api/v1/events/export"])
@pytest.mark.parametrize("role", ["member", None])
def test_non_admin_is_refused(
    path: str, role: str | None, membership_role: dict[str, str | None]
) -> None:
    membership_role["value"] = role
    assert _client().get(path).status_code == 403


def test_demoted_admin_is_refused_despite_admin_token(
    membership_role: dict[str, str | None],
) -> None:
    membership_role["value"] = "member"
    assert _client({**ADMIN, "role": "admin"}).get("/api/v1/events").status_code == 403


def test_bot_token_is_refused(membership_role: dict[str, str | None]) -> None:
    bot = {"email": BOT_SERVICE_EMAIL, "org_id": "org-1", "role": "admin"}
    assert _client(bot).get("/api/v1/events").status_code == 403


def test_membership_lookup_failure_is_503_not_403() -> None:
    with patch.object(
        events_router.member_service,
        "get_membership",
        side_effect=ServerSelectionTimeoutError("db down"),
    ) as lookup:
        response = _client().get("/api/v1/events")

    assert response.status_code == 503
    assert lookup.call_args.kwargs == {"strict": True}


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_admins_can_read(
    role: str, membership_role: dict[str, str | None], fake_store: FakeStore
) -> None:
    membership_role["value"] = role
    assert _client().get("/api/v1/events").status_code == 200


# --- listing ------------------------------------------------------------------


def test_list_is_scoped_to_token_org_and_passes_filters(
    membership_role: dict[str, str | None], fake_store: FakeStore
) -> None:
    response = _client().get(
        "/api/v1/events",
        params=[
            ("type", "call.recording.viewed"),
            ("type", "call.transcript.viewed"),
            ("actor_id", "jane@example.com"),
            ("target_type", "call"),
            ("target_id", "call-1"),
            ("resource", "agent:agent-1"),
            ("org_id", "org-2"),
            ("from", "2026-11-01T00:00:00Z"),
            ("to", "2026-11-20T00:00:00+05:30"),
            ("limit", "10"),
        ],
    )

    assert response.status_code == 200
    [call] = fake_store.reads
    flt: EventFilter = call["filter"]
    assert flt.org_id == "org-1"
    assert flt.types == ("call.recording.viewed", "call.transcript.viewed")
    assert (flt.actor_id, flt.target_type, flt.target_id) == ("jane@example.com", "call", "call-1")
    assert flt.resource == "agent:agent-1"
    assert flt.start == datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert flt.end == datetime(2026, 11, 19, 18, 30, tzinfo=timezone.utc)
    assert call["limit"] == 10


def test_list_defaults_to_last_30_days(
    membership_role: dict[str, str | None], fake_store: FakeStore
) -> None:
    _client().get("/api/v1/events")
    flt: EventFilter = fake_store.reads[0]["filter"]
    assert flt.end - flt.start == timedelta(days=30)
    assert datetime.now(timezone.utc) - flt.end < timedelta(minutes=1)


def test_future_to_is_treated_as_now(
    membership_role: dict[str, str | None], fake_store: FakeStore
) -> None:
    # Past 2106, ObjectId timestamps overflow; the bound must never reach the store.
    response = _client().get("/api/v1/events", params={"to": "2200-01-01T00:00:00Z"})

    assert response.status_code == 200
    flt: EventFilter = fake_store.reads[0]["filter"]
    assert datetime.now(timezone.utc) - flt.end < timedelta(minutes=1)
    assert flt.end - flt.start == timedelta(days=30)


def test_export_with_future_to_records_and_streams(
    membership_role: dict[str, str | None],
    fake_store: FakeStore,
    emitted: list[dict[str, Any]],
) -> None:
    response = _client().get("/api/v1/events/export", params={"to": "2200-01-01T00:00:00Z"})
    assert response.status_code == 200
    assert len(emitted) == 1


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2025-01-01T00:00:00Z", "to": "2026-11-20T00:00:00Z"},
        {"from": "2026-11-20T00:00:00Z", "to": "2026-11-01T00:00:00Z"},
        {"from": "1960-01-01T00:00:00Z", "to": "1960-02-01T00:00:00Z"},
        {"to": "1960-02-01T00:00:00Z"},
        {"type": "call.unknown.viewed"},
        {"cursor": "not-an-object-id"},
    ],
)
def test_invalid_range_or_cursor_is_rejected(
    params: dict[str, str],
    membership_role: dict[str, str | None],
    fake_store: FakeStore,
) -> None:
    assert _client().get("/api/v1/events", params=params).status_code == 400


@pytest.mark.parametrize("limit", [0, 201])
def test_limit_bounds(limit: int, membership_role: dict[str, str | None]) -> None:
    assert _client().get("/api/v1/events", params={"limit": limit}).status_code == 422


@pytest.mark.parametrize("name", ["actor_id", "target_type", "target_id"])
def test_overlong_filters_are_rejected(name: str, membership_role: dict[str, str | None]) -> None:
    params = {name: "x" * (events_router.MAX_FILTER_LENGTH + 1)}
    assert _client().get("/api/v1/events", params=params).status_code == 422


def test_list_serialises_events_and_cursor(
    membership_role: dict[str, str | None], fake_store: FakeStore
) -> None:
    fake_store.docs.extend(_event(i) for i in range(3))
    fake_store.docs[0]["related"] = [{"type": "agent", "id": "agent-1", "name": "Support Bot"}]
    fake_store.docs[0]["resource_keys"] = ["call:call-0", "agent:agent-1"]

    full = _client().get("/api/v1/events", params={"limit": 2}).json()
    last = _client().get(
        "/api/v1/events", params={"limit": 2, "cursor": full["next_cursor"]}
    ).json()

    assert [e["id"] for e in full["events"]] == [str(d["_id"]) for d in fake_store.docs[:2]]
    assert full["events"][0]["ts"] == "2026-11-20T09:41:12.381Z"
    assert full["events"][0]["actor"]["id"] == "jane@example.com"
    assert full["events"][0]["related"] == [{"type": "agent", "id": "agent-1", "name": "Support Bot"}]
    assert "resource_keys" not in full["events"][0]
    # A resource without a name (calls) omits the key instead of returning null.
    assert full["events"][0]["target"] == {"type": "call", "id": "call-0"}
    assert full["events"][1]["related"] == []
    assert full["next_cursor"] == full["events"][-1]["id"]
    assert fake_store.reads[1]["before"] == ObjectId(full["next_cursor"])
    assert len(last["events"]) == 2  # fake store ignores the cursor

    fake_store.docs.pop()
    fake_store.docs.pop()
    short = _client().get("/api/v1/events", params={"limit": 2}).json()
    assert short["next_cursor"] is None


def test_types_lists_registry(membership_role: dict[str, str | None]) -> None:
    body = _client().get("/api/v1/events/types").json()
    assert {t["name"] for t in body} == set(REGISTRY)
    assert all(t["description"] for t in body)


# --- export -------------------------------------------------------------------


def _csv(response_text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(response_text)))


def test_export_streams_csv_and_records_export(
    membership_role: dict[str, str | None],
    fake_store: FakeStore,
    emitted: list[dict[str, Any]],
) -> None:
    fake_store.docs.append(
        _event(
            0,
            target={"type": "call", "id": "call-0", "name": "Call 0"},
            related=[{"type": "agent", "id": "agent-1", "name": "Support Bot"}, {"type": "campaign", "id": "camp-1"}],
        )
    )

    response = _client().get(
        "/api/v1/events/export",
        params=[
            ("type", "call.transcript.viewed"),
            ("target_id", "call-0"),
            ("resource", "agent:agent-1"),
        ],
        headers={"User-Agent": "pytest"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith('attachment; filename="audit-log-')
    header, row = _csv(response.text)
    assert tuple(header) == events_router.CSV_COLUMNS
    assert dict(zip(header, row)) == {
        "id": str(fake_store.docs[0]["_id"]),
        "ts": "2026-11-20T09:41:12.381Z",
        "type": "call.transcript.viewed",
        "outcome": "success",
        "actor_type": "user",
        "actor_id": "jane@example.com",
        "actor_role": "admin",
        "target_type": "call",
        "target_id": "call-0",
        "target_name": "Call 0",
        "related": "agent:agent-1 (Support Bot); campaign:camp-1",
        "ip": "203.0.113.7",
        "user_agent": "",
        "data": '{"object_key":"k"}',
    }

    [event] = emitted
    assert event["type"] == "events.exported"
    assert event["org_id"] == "org-1"
    assert event["actor"]["id"] == "admin@example.com"
    assert event["context"]["user_agent"] == "pytest"
    assert event["data"]["types"] == ["call.transcript.viewed"]
    assert event["data"]["resource"] == "agent:agent-1"
    assert event["data"]["target_id"] == "call-0"
    assert "actor_id" not in event["data"]


def test_list_does_not_emit(
    membership_role: dict[str, str | None],
    fake_store: FakeStore,
    emitted: list[dict[str, Any]],
) -> None:
    _client().get("/api/v1/events")
    assert emitted == []


def test_export_escapes_formula_cells(
    membership_role: dict[str, str | None],
    fake_store: FakeStore,
    emitted: list[dict[str, Any]],
) -> None:
    fake_store.docs.append(
        _event(
            actor={"type": "user", "id": "=HYPERLINK(1)", "role": "+admin"},
            target={"type": "call", "id": "-1"},
            context={"ip": "@x", "user_agent": "\tua"},
        )
    )

    _, row = _csv(_client().get("/api/v1/events/export").text)
    values = dict(zip(events_router.CSV_COLUMNS, row))
    assert values["actor_id"] == "'=HYPERLINK(1)"
    assert values["actor_role"] == "'+admin"
    assert values["target_id"] == "'-1"
    assert values["ip"] == "'@x"
    assert values["user_agent"] == "'\tua"


def test_export_is_capped_with_truncation_marker(
    membership_role: dict[str, str | None],
    fake_store: FakeStore,
    emitted: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EVENTLOG_EXPORT_MAX_ROWS", 2)
    fake_store.docs.extend(_event(i) for i in range(5))

    rows = _csv(_client().get("/api/v1/events/export").text)

    assert len(rows) == 4
    assert rows[-1] == ["# truncated: export is limited to 2 rows"]
    assert fake_store.reads[0]["limit"] == 3


def test_export_at_cap_has_no_marker(
    membership_role: dict[str, str | None],
    fake_store: FakeStore,
    emitted: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EVENTLOG_EXPORT_MAX_ROWS", 2)
    fake_store.docs.extend(_event(i) for i in range(2))

    rows = _csv(_client().get("/api/v1/events/export").text)

    assert len(rows) == 3
    assert not rows[-1][0].startswith("#")


@pytest.mark.parametrize("value", ["agent", ":agent-1", "Agent:agent-1", "agent:"])
def test_malformed_resource_filter_is_rejected(
    value: str, membership_role: dict[str, str | None]
) -> None:
    assert _client().get("/api/v1/events", params={"resource": value}).status_code == 422


def test_unknown_resource_type_is_rejected(membership_role: dict[str, str | None]) -> None:
    response = _client().get("/api/v1/events", params={"resource": "phone:+911234"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown resource type: phone"


def test_resource_filter_accepts_every_storable_key(
    membership_role: dict[str, str | None], fake_store: FakeStore
) -> None:
    from app.services.eventlog import MAX_TARGET_ID_LENGTH, registry, resource_key

    for resource_type in registry.RESOURCE_TYPES:
        key = resource_key(resource_type, "x" * MAX_TARGET_ID_LENGTH)
        assert len(key) <= events_router.MAX_RESOURCE_FILTER_LENGTH
    longest = resource_key("campaign", "x" * MAX_TARGET_ID_LENGTH)
    response = _client().get("/api/v1/events", params={"resource": longest})
    assert response.status_code == 200
