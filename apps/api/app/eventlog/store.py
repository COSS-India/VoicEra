"""The only module that queries the ``Events`` collection."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pymongo
from bson import ObjectId
from pymongo.collection import Collection

from app.config import settings
from app.database import get_database

logger = logging.getLogger("voicera.eventlog")

COLLECTION = "Events"
SLOW_WRITE_MS = 10
INITIAL_WINDOW = timedelta(days=1)
PURGE_CHUNK_SIZE = 5_000


@dataclass(frozen=True)
class EventFilter:
    """Org-scoped query. ``start`` and ``end`` are inclusive, to the second."""

    org_id: str
    start: datetime
    end: datetime
    types: tuple[str, ...] = ()
    actor_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None

    def match(self) -> dict[str, Any]:
        query: dict[str, Any] = {"org_id": self.org_id}
        if len(self.types) == 1:
            query["type"] = self.types[0]
        elif self.types:
            query["type"] = {"$in": list(self.types)}
        if self.actor_id:
            query["actor.id"] = self.actor_id
        if self.target_id:
            query["target.id"] = self.target_id
        if self.target_type:
            query["target.type"] = self.target_type
        return query


def _collection() -> Collection:
    return get_database()[COLLECTION]


def insert(event: dict[str, Any]) -> None:
    """Insert one event, bounded by ``EVENTLOG_WRITE_TIMEOUT_MS``."""
    started = time.perf_counter()
    with pymongo.timeout(settings.EVENTLOG_WRITE_TIMEOUT_MS / 1000):
        _collection().insert_one(event)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms > SLOW_WRITE_MS:
        logger.warning(
            "eventlog slow write: %.1f ms",
            elapsed_ms,
            extra={"eventlog_slow_write_ms": round(elapsed_ms, 1)},
        )


def iterate(
    flt: EventFilter,
    *,
    limit: int,
    before: ObjectId | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield up to ``limit`` events newest-first, optionally strictly before ``before``.

    DocumentDB sorts every row an index returns before applying ``limit``, so
    reads walk back from the upper bound in time windows that start at one day
    and double. Each page then costs the rows in its last window, not the
    organisation's whole history. A ``target_id`` filter matches only a few
    rows, so it reads the whole range in one query.
    """
    lower = ObjectId.from_datetime(flt.start)
    upper = ObjectId.from_datetime(flt.end + timedelta(seconds=1))
    if before is not None and before < upper:
        upper = before

    match = flt.match()
    window = INITIAL_WINDOW
    remaining = limit
    while remaining > 0 and upper > lower:
        window_start = upper.generation_time - window
        start = (
            lower
            if flt.target_id or window_start <= flt.start
            else ObjectId.from_datetime(window_start)
        )
        cursor = (
            _collection()
            .find({**match, "_id": {"$gte": start, "$lt": upper}})
            .sort("_id", pymongo.DESCENDING)
            .limit(remaining)
        )
        for doc in cursor:
            yield doc
            remaining -= 1
        upper = start
        window *= 2


def purge(before: datetime) -> int:
    """Delete events created before ``before`` in chunks on the ``_id`` primary key."""
    cutoff = {"_id": {"$lt": ObjectId.from_datetime(before)}}
    collection = _collection()
    deleted = 0
    while True:
        ids = [
            doc["_id"]
            for doc in collection.find(cutoff, {"_id": 1}).limit(PURGE_CHUNK_SIZE)
        ]
        if not ids:
            return deleted
        count = collection.delete_many({"_id": {"$in": ids}}).deleted_count
        if not count:
            return deleted
        deleted += count
