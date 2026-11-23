"""Unit tests for app.services.eventlog: envelope, fallback, registry, settings."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from app.services import eventlog
from app.auth import BOT_SERVICE_EMAIL
from app.config import Settings
from app.services.eventlog import (
    Actor,
    Resource,
    Target,
    emit,
    emit_many,
    registry,
    request_context,
    store,
)
from app.services.eventlog.registry import CALL_TRANSCRIPT_VIEWED, REGISTRY, EventType
from bson import ObjectId
from pydantic import ValidationError
from pymongo.errors import NetworkTimeout


def _fallback_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    lines = []
    for record in caplog.records:
        if record.name == "voicera.eventlog" and '"eventlog_fallback"' in record.getMessage():
            lines.append(json.loads(record.getMessage()))
    return lines


@pytest.fixture
def inserted() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with patch.object(store, "insert", side_effect=events.append):
        yield events


def _emit(**overrides: Any) -> None:
    kwargs: dict[str, Any] = {
        "org_id": "org-1",
        "actor": Actor("user", "jane@example.com", "admin"),
        "target": Target("call", "call-1"),
        "related": [Resource("agent", "agent-1", "Support Bot")],
        "data": {"object_key": "k"},
        "context": {"ip": "203.0.113.7"},
    }
    kwargs.update(overrides)
    emit(CALL_TRANSCRIPT_VIEWED, **kwargs)


def test_emit_builds_envelope(inserted: list[dict[str, Any]]) -> None:
    _emit()

    [event] = inserted
    assert isinstance(event["_id"], ObjectId)
    assert isinstance(event["ts"], datetime) and event["ts"].tzinfo is timezone.utc
    assert event["ts"].microsecond % 1000 == 0
    assert event == {
        "_id": event["_id"],
        "ts": event["ts"],
        "v": 1,
        "org_id": "org-1",
        "type": "call.transcript.viewed",
        "source": "api",
        "actor": {"type": "user", "id": "jane@example.com", "role": "admin"},
        "target": {"type": "call", "id": "call-1"},
        "related": [{"type": "agent", "id": "agent-1", "name": "Support Bot"}],
        "resource_keys": ["call:call-1", "agent:agent-1"],
        "outcome": "success",
        "context": {"ip": "203.0.113.7"},
        "data": {"object_key": "k"},
    }


def test_emit_omits_empty_optional_fields(inserted: list[dict[str, Any]]) -> None:
    _emit(target=None, related=(), data=None, context={})
    assert not {"target", "related", "resource_keys", "data", "context"} & inserted[0].keys()


def test_resource_without_name_omits_it(inserted: list[dict[str, Any]]) -> None:
    _emit(target=Target("call", "call-1"), related=[Resource("agent", "agent-1")])
    assert inserted[0]["target"] == {"type": "call", "id": "call-1"}
    assert inserted[0]["related"] == [{"type": "agent", "id": "agent-1"}]


def test_related_duplicates_and_target_are_not_repeated(inserted: list[dict[str, Any]]) -> None:
    agent = Resource("agent", "agent-1", "Support Bot")
    _emit(related=[Resource("call", "call-1"), agent, agent])
    [event] = inserted
    assert event["related"] == [{"type": "agent", "id": "agent-1", "name": "Support Bot"}]
    assert event["resource_keys"] == ["call:call-1", "agent:agent-1"]


def test_resource_key_matches_stored_keys() -> None:
    assert eventlog.resource_key("agent", "agent-1") == "agent:agent-1"


@pytest.mark.parametrize(
    "related",
    [
        [Resource("Agent", "agent-1")],
        [Resource("agent:x", "agent-1")],
        [Resource("phone", "agent-1")],
        [Resource("agent", "")],
        [Resource("agent", f"agent-{i}") for i in range(eventlog.MAX_RELATED + 1)],
    ],
)
def test_invalid_related_falls_back_without_writing(
    related: list[Resource], inserted: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    _emit(related=related)
    assert inserted == []
    assert "build_failed" in caplog.text


def test_actor_from_user_distinguishes_bot_service() -> None:
    user = Actor.from_user({"email": "a@example.com", "role": "member"})
    bot = Actor.from_user({"email": BOT_SERVICE_EMAIL, "role": "admin"})
    assert user == Actor("user", "a@example.com", "member")
    assert bot == Actor("service", BOT_SERVICE_EMAIL, "admin")


def test_request_context_omits_absent_values() -> None:
    request = MagicMock()
    request.client = None
    request.headers = {}
    assert request_context(request) == {}

    request.client = MagicMock(host="198.51.100.1")
    request.headers = {"user-agent": "pytest"}
    assert request_context(request) == {"ip": "198.51.100.1", "user_agent": "pytest"}


def test_request_supplied_values_are_bounded(inserted: list[dict[str, Any]]) -> None:
    _emit(
        target=Target("call", "x" * 10_000),
        related=[Resource("agent", "a" * 10_000, "n" * 10_000)],
        context={"user_agent": "u" * 10_000},
    )

    [event] = inserted
    assert len(event["target"]["id"]) == eventlog.MAX_TARGET_ID_LENGTH
    assert len(event["related"][0]["id"]) == eventlog.MAX_TARGET_ID_LENGTH
    assert len(event["related"][0]["name"]) == eventlog.MAX_RESOURCE_NAME_LENGTH
    assert event["resource_keys"][1] == "agent:" + "a" * eventlog.MAX_TARGET_ID_LENGTH
    assert len(event["context"]["user_agent"]) == eventlog.MAX_CONTEXT_VALUE_LENGTH


@pytest.mark.parametrize(
    "overrides",
    [
        {"org_id": ""},
        {"outcome": "denied"},
        {"actor": None},
    ],
)
def test_emit_never_raises_on_bad_input(
    overrides: dict[str, Any],
    inserted: list[dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _emit(**overrides)

    assert inserted == []
    [line] = _fallback_lines(caplog)
    assert line["reason"] == "build_failed"
    assert "event" not in line


def test_emit_rejects_unregistered_type(
    inserted: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    emit(EventType("call.recording.viewed", "copy"), org_id="o", actor=Actor("user", "a"))
    assert inserted == []
    assert _fallback_lines(caplog)[0]["reason"] == "build_failed"


@pytest.mark.parametrize("error", [RuntimeError("db down"), NetworkTimeout("timed out")])
def test_emit_never_raises_on_write_failure(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    with patch.object(store, "insert", side_effect=error):
        _emit()

    [line] = _fallback_lines(caplog)
    assert line["reason"] == "write_failed"
    assert type(error).__name__ in line["error"]
    assert line["event"]["type"] == "call.transcript.viewed"
    # Extended JSON keeps the ObjectId, so a replayed line is idempotent.
    assert ObjectId.is_valid(line["event"]["_id"]["$oid"])


def test_emit_on_event_loop_logs_error(
    inserted: list[dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
    eventlog_loop_guard: Any,
) -> None:
    async def produce() -> None:
        _emit()

    asyncio.run(produce())

    assert len(inserted) == 1
    assert eventlog.EVENT_LOOP_WARNING in caplog.messages
    assert eventlog_loop_guard.seen
    eventlog_loop_guard.seen = False  # expected here; the shared guard fails everywhere else


def test_slow_write_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    collection = MagicMock()
    collection.insert_one.side_effect = lambda _event: time.sleep(0.02)
    with patch.object(store, "_collection", return_value=collection):
        store.insert({"_id": ObjectId()})

    [record] = [r for r in caplog.records if r.getMessage().startswith("eventlog slow write")]
    assert record.levelno == logging.WARNING
    assert record.eventlog_slow_write_ms >= 20


def _emit_many(count: int) -> None:
    emit_many(
        CALL_TRANSCRIPT_VIEWED,
        org_id="org-1",
        actor=Actor("user", "jane@example.com", "admin"),
        related=[Resource("agent", "agent-1", "Support Bot")],
        context={"ip": "203.0.113.7"},
        items=((Target("call", f"call-{i}"), {"n": i}) for i in range(count)),
    )


def test_emit_many_writes_unordered_batches() -> None:
    batches: list[list[dict[str, Any]]] = []
    with patch.object(store, "insert_many", side_effect=batches.append):
        _emit_many(eventlog.BATCH_SIZE * 2 + 1)

    assert [len(b) for b in batches] == [eventlog.BATCH_SIZE, eventlog.BATCH_SIZE, 1]
    events = [event for batch in batches for event in batch]
    assert [e["target"]["id"] for e in events] == [f"call-{i}" for i in range(len(events))]
    assert len({e["_id"] for e in events}) == len(events)
    first = events[0]
    assert first["type"] == "call.transcript.viewed"
    assert first["org_id"] == "org-1"
    assert first["actor"] == {"type": "user", "id": "jane@example.com", "role": "admin"}
    assert first["context"] == {"ip": "203.0.113.7"}
    assert first["data"] == {"n": 0}
    assert all(e["related"] == [{"type": "agent", "id": "agent-1", "name": "Support Bot"}] for e in events)
    assert events[0]["resource_keys"] == ["call:call-0", "agent:agent-1"]


def test_emit_many_with_no_items_writes_nothing() -> None:
    with patch.object(store, "insert_many") as insert_many:
        _emit_many(0)
    insert_many.assert_not_called()


def test_emit_many_falls_back_for_whole_batch_on_write_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with patch.object(store, "insert_many", side_effect=NetworkTimeout("timed out")):
        _emit_many(3)

    lines = _fallback_lines(caplog)
    assert [line["event"]["target"]["id"] for line in lines] == ["call-0", "call-1", "call-2"]
    assert all(ObjectId.is_valid(line["event"]["_id"]["$oid"]) for line in lines)


def test_registry_names_are_unique_and_well_formed() -> None:
    declared = [v for v in vars(registry).values() if isinstance(v, EventType)]
    assert len(declared) == len(REGISTRY)
    for event_type in declared:
        assert REGISTRY[event_type.name] is event_type
        assert registry.NAME_PATTERN.match(event_type.name), event_type.name
        assert event_type.description


def test_resource_types_are_well_formed() -> None:
    for resource_type in registry.RESOURCE_TYPES:
        assert registry.RESOURCE_TYPE_PATTERN.match(resource_type), resource_type


def test_unregistered_target_type_falls_back_without_writing(
    inserted: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    _emit(target=Target("phone", "x"))
    assert inserted == []
    assert "unregistered resource type: 'phone'" in caplog.text


def test_retention_below_one_year_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(EVENTLOG_RETENTION_DAYS=364)
    assert Settings(EVENTLOG_RETENTION_DAYS=400).EVENTLOG_RETENTION_DAYS == 400


def test_public_api() -> None:
    assert set(eventlog.__all__) >= {"emit", "Actor", "Resource", "Target", "request_context", "resource_key"}


def test_non_string_target_id_is_stored_and_keyed(inserted: list[dict[str, Any]]) -> None:
    _emit(target=Target("call", ObjectId("6743a1c8e4b0f1a2b3c4d5e6")), related=())
    [event] = inserted
    assert event["target"]["id"] == "6743a1c8e4b0f1a2b3c4d5e6"
    assert event["resource_keys"] == ["call:6743a1c8e4b0f1a2b3c4d5e6"]
