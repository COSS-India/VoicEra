"""Event store against a real FerretDB / DocumentDB.

Uses a throwaway database that is dropped afterwards. Run with:

    EVENTLOG_TEST_MONGODB_URI=mongodb://admin:<password>@localhost:27018/ \\
    python -m pytest apps/api/tests/test_eventlog_store_integration.py -q
"""

from __future__ import annotations

import os
import struct
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from app.database_init import _ensure_events
from app.services.eventlog import Actor, Target, emit, store
from app.services.eventlog.registry import CALL_RECORDING_VIEWED, CALL_TRANSCRIPT_VIEWED
from app.services.eventlog.store import EventFilter
from bson import ObjectId
from pymongo import MongoClient
from pymongo.database import Database

MONGODB_URI = os.getenv("EVENTLOG_TEST_MONGODB_URI", "")

pytestmark = pytest.mark.skipif(
    not MONGODB_URI, reason="Set EVENTLOG_TEST_MONGODB_URI to run event store integration tests"
)

NOW = datetime.now(timezone.utc).replace(microsecond=0)
EVENT_INDEXES = {"org_id_desc", "org_type_id", "org_actor_id", "org_target_id", "org_resource_keys"}


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    client: MongoClient = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=3000)
    database = client[f"eventlog_test_{uuid.uuid4().hex[:8]}"]
    _ensure_events(database, set())
    try:
        yield database
    finally:
        client.drop_database(database.name)
        client.close()


@pytest.fixture
def events(db: Database, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setattr(store, "_collection", lambda: db["Events"])
    yield db["Events"]
    db["Events"].delete_many({})


def _oid_at(when: datetime) -> ObjectId:
    """A unique ObjectId whose timestamp is ``when``."""
    return ObjectId(struct.pack(">I", int(when.timestamp())) + os.urandom(8))


def _doc(when: datetime, org_id: str = "org-1", **fields: Any) -> dict[str, Any]:
    target_id = fields.pop("target_id", "call-1")
    related = fields.pop("related", [])
    return {
        "_id": _oid_at(when),
        "v": 1,
        "org_id": org_id,
        "type": fields.pop("type", "call.recording.viewed"),
        "ts": when,
        "source": "api",
        "actor": {"type": "user", "id": fields.pop("actor_id", "a@example.com")},
        "target": {"type": "call", "id": target_id},
        "resource_keys": [f"call:{target_id}", *(f"{r['type']}:{r['id']}" for r in related)],
        "outcome": "success",
        **({"related": related} if related else {}),
        **fields,
    }


def _filter(days: int = 30, **kwargs: Any) -> EventFilter:
    return EventFilter(
        org_id=kwargs.pop("org_id", "org-1"),
        start=NOW - timedelta(days=days),
        end=NOW,
        **kwargs,
    )


def _page(flt: EventFilter, limit: int, before: ObjectId | None = None) -> list[dict[str, Any]]:
    return list(store.iterate(flt, limit=limit, before=before))


class _CountingCollection:
    """Records each ``find`` filter, then delegates to the real collection."""

    def __init__(self, find: Any, queries: list[dict[str, Any]]) -> None:
        self._find = find
        self._queries = queries

    def find(self, query: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        self._queries.append(query)
        return self._find(query, *args, **kwargs)


def test_indexes_are_ordered(db: Database) -> None:
    info = db["Events"].index_information()
    assert EVENT_INDEXES <= info.keys()
    for name in EVENT_INDEXES:
        assert info[name].get("enableOrderedIndex"), name
        assert info[name]["key"][0] == ("org_id", 1)
        assert info[name]["key"][-1] == ("_id", -1)


def test_emit_writes_through_bounded_insert(events: Any) -> None:
    emit(
        CALL_TRANSCRIPT_VIEWED,
        org_id="org-1",
        actor=Actor("user", "a@example.com", "admin"),
        target=Target("call", "call-9"),
    )
    [doc] = list(events.find())
    assert doc["type"] == "call.transcript.viewed"
    assert doc["target"] == {"type": "call", "id": "call-9"}


def test_pages_continue_without_gap_or_overlap_within_one_second(events: Any) -> None:
    second = NOW - timedelta(hours=1)
    events.insert_many([_doc(second, target_id=f"c{i}") for i in range(7)])
    events.insert_many([_doc(second - timedelta(seconds=1)) for _ in range(3)])

    seen: list[ObjectId] = []
    cursor = None
    while True:
        page = _page(_filter(), 3, cursor)
        seen.extend(doc["_id"] for doc in page)
        if len(page) < 3:
            break
        cursor = page[-1]["_id"]

    assert len(seen) == 10 == len(set(seen))
    assert seen == sorted(seen, reverse=True)


def test_sparse_org_fills_page_across_doubling_windows(events: Any) -> None:
    events.insert_many([_doc(NOW - timedelta(days=d)) for d in (2, 9, 40, 200, 360)])
    events.insert_many([_doc(NOW - timedelta(days=1), org_id="org-2") for _ in range(5)])

    page = _page(_filter(days=366), 5)

    assert [d["org_id"] for d in page] == ["org-1"] * 5
    assert [d["_id"] for d in page] == sorted((d["_id"] for d in page), reverse=True)


def test_dense_org_fills_page_from_first_window(events: Any) -> None:
    events.insert_many([_doc(NOW - timedelta(minutes=m)) for m in range(1, 60)])
    assert len(_page(_filter(), 50)) == 50


def test_reading_stops_at_from(events: Any) -> None:
    events.insert_many([_doc(NOW - timedelta(days=d)) for d in (1, 5, 31, 60)])
    page = _page(_filter(days=30), 50)
    assert len(page) == 2


def test_to_is_inclusive_of_its_second(events: Any) -> None:
    events.insert_one(_doc(NOW))
    assert len(_page(_filter(), 50)) == 1


G1 = {"type": "agent", "id": "g1", "name": "Support Bot"}


def test_filters_use_type_actor_target_and_resource(events: Any) -> None:
    hour = NOW - timedelta(hours=1)
    events.insert_many(
        [
            _doc(hour, type="call.recording.viewed", actor_id="a", target_id="t1", related=[G1]),
            _doc(hour, type="call.transcript.viewed", actor_id="b", target_id="t1", related=[G1]),
            _doc(hour, type="call.transcript.downloaded", actor_id="a", target_id="t2"),
        ]
    )

    def count(**kwargs: Any) -> int:
        return len(_page(_filter(**kwargs), 50))

    assert count(types=(CALL_RECORDING_VIEWED.name,)) == 1
    assert count(types=("call.recording.viewed", "call.transcript.viewed")) == 2
    assert count(actor_id="a") == 2
    assert count(target_id="t1", target_type="call") == 2
    assert count(target_id="t1", target_type="agent") == 0
    assert count(actor_id="a", target_id="t2") == 1
    assert count(resource="agent:g1") == 2
    assert count(resource="agent:g1", actor_id="b") == 1
    assert count(resource="agent:g2") == 0
    # The target is a resource too.
    assert count(resource="call:t2") == 1


def test_target_filter_reads_whole_range_in_one_query(
    events: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    events.insert_many([_doc(NOW - timedelta(days=d), target_id="t9") for d in (1, 100, 300)])
    queries: list[dict[str, Any]] = []
    real = events.find
    monkeypatch.setattr(store, "_collection", lambda: _CountingCollection(real, queries))

    page = _page(_filter(days=366, target_id="t9"), 50)

    assert len(page) == 3
    assert len(queries) == 1


def test_window_never_steps_before_the_epoch(events: Any) -> None:
    flt = EventFilter(
        org_id="org-1",
        start=datetime(1970, 1, 2, tzinfo=timezone.utc),
        end=datetime(1971, 6, 1, tzinfo=timezone.utc),
    )
    assert _page(flt, 50) == []


def test_purge_deletes_only_older_events_in_chunks(
    events: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store, "PURGE_CHUNK_SIZE", 3)
    cutoff = NOW - timedelta(days=365)
    events.insert_many([_doc(cutoff - timedelta(days=d)) for d in range(1, 8)])
    events.insert_many([_doc(cutoff + timedelta(days=d)) for d in range(1, 4)])

    assert store.purge(cutoff) == 7
    assert events.count_documents({}) == 3
    assert store.purge(cutoff) == 0
