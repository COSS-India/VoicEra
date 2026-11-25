"""Registered event and resource types. ``emit()`` only accepts types declared here."""

from __future__ import annotations

import re
from dataclasses import dataclass

NAME_PATTERN = re.compile(r"^[a-z][a-z_]*(\.[a-z][a-z_]*)+$")
# Resource types never contain ``:``, so a ``"type:id"`` resource key splits unambiguously.
RESOURCE_TYPE_PATTERN = re.compile(r"^[a-z][a-z_]*$")

# Types an event's ``target`` and ``related`` resources may have. One name per kind
# of thing, so a ``resource`` filter finds every event about it; add new kinds here.
RESOURCE_TYPES: frozenset[str] = frozenset({"agent", "call", "campaign"})


@dataclass(frozen=True)
class EventType:
    name: str
    description: str


CALL_RECORDING_VIEWED = EventType(
    "call.recording.viewed", "Call recording viewed"
)
CALL_RECORDING_DOWNLOADED = EventType(
    "call.recording.downloaded", "Call recording downloaded"
)
CALL_PROVIDER_RECORDING_VIEWED = EventType(
    "call.provider_recording.viewed", "Provider call recording viewed"
)
CALL_PROVIDER_RECORDING_DOWNLOADED = EventType(
    "call.provider_recording.downloaded", "Provider call recording downloaded"
)
CALL_TRANSCRIPT_VIEWED = EventType(
    "call.transcript.viewed", "Call transcript viewed"
)
CALL_TRANSCRIPT_DOWNLOADED = EventType(
    "call.transcript.downloaded", "Call transcript downloaded"
)
EVENTS_EXPORTED = EventType("events.exported", "Audit log exported")

REGISTRY: dict[str, EventType] = {
    t.name: t
    for t in (
        CALL_RECORDING_VIEWED,
        CALL_RECORDING_DOWNLOADED,
        CALL_PROVIDER_RECORDING_VIEWED,
        CALL_PROVIDER_RECORDING_DOWNLOADED,
        CALL_TRANSCRIPT_VIEWED,
        CALL_TRANSCRIPT_DOWNLOADED,
        EVENTS_EXPORTED,
    )
}
