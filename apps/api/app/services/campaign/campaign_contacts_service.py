"""Per-contact view of a campaign: one entry per CSV row, with its calls.

Each CSV row becomes one root ``QueuedRuns`` document (``parent_queued_run_id``
is null). A retry is a new run whose ``parent_queued_run_id`` points at the
attempt before it, so a contact's attempts form a chain under its root.
This module pages over the roots in upload order, walks each chain, joins
the calls, and reports one status per contact — the VoicEra equivalent of
Raya's ``GET /api/batch/{id}/contacts``.
"""

from __future__ import annotations

import re
from typing import Any

from app.database import get_database

QUEUED_RUNS = "QueuedRuns"
CALL_LOGS = "CallLogs"

_ROW = re.compile(r"_row_(\d+)")
_RETRY_KEYS = frozenset({"is_retry", "retry_attempt", "retry_reason"})
_UNANSWERED = frozenset({"busy", "no_answer", "cancelled", "voicemail"})
_TERMINAL_CALL = frozenset({"completed", "failed"})
_MAX_RETRY_DEPTH = 20

CONTACT_STATUSES = (
    "pending",      # not called yet
    "in_progress",  # being dialled or on a call
    "retrying",     # called before; another attempt is queued
    "completed",    # the latest call was answered
    "unanswered",   # the latest call was busy / not answered, no retry queued
    "failed",       # could not be dialled, or the call failed
    "invalid",      # the row has no phone number; never dialled
)


def _row_number(source_uuid: str) -> int | None:
    match = _ROW.search(source_uuid or "")
    return int(match.group(1)) if match else None


def _contact_status(root: dict[str, Any], latest: dict[str, Any], attempts: int,
                    calls: dict[str, dict[str, Any]]) -> str:
    if root.get("state") == "invalid":
        return "invalid"
    state = latest.get("state")
    call_id = latest.get("call_id")
    if state == "queued":
        return "retrying" if attempts else "pending"
    if not call_id:
        return "failed" if state == "failed" else "in_progress"
    call = calls.get(call_id)
    if not call:
        return "in_progress"
    if call.get("call_response") == "answered":
        return "completed"
    if call.get("status") not in _TERMINAL_CALL:
        return "in_progress"
    if call.get("call_response") in _UNANSWERED:
        return "unanswered"
    return "failed"


def _contact(root: dict[str, Any], chain: list[dict[str, Any]],
             calls: dict[str, dict[str, Any]]) -> dict[str, Any]:
    runs = sorted(chain, key=lambda run: int(run.get("retry_count") or 0))
    attempts: list[dict[str, Any]] = []
    for run in runs:
        call_id = run.get("call_id")
        if not call_id:
            continue
        call = calls.get(call_id) or {}
        attempts.append(
            {
                "attempt": len(attempts) + 1,
                "call_id": call_id,
                "queued_run_id": run.get("queued_run_id"),
                "status": call.get("status"),
                "call_response": call.get("call_response"),
                "start_time_utc": call.get("start_time_utc"),
                "duration": call.get("duration"),
            }
        )
    variables = {
        key: value
        for key, value in (root.get("context_variables") or {}).items()
        if key not in _RETRY_KEYS
    }
    source_uuid = str(root.get("source_uuid") or "")
    return {
        "row": _row_number(source_uuid),
        "contact_id": root.get("queued_run_id"),
        "phone_number": variables.get("phone_number") or None,
        "variables": variables,
        "status": _contact_status(root, runs[-1], len(attempts), calls),
        "invalid_reason": root.get("invalid_reason"),
        "attempts": len(attempts),
        "last_call_id": attempts[-1]["call_id"] if attempts else None,
        "calls": attempts,
    }


def list_campaign_contacts(
    org_id: str,
    campaign_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
    db: Any = None,
) -> dict[str, Any]:
    """One page of contacts in upload order. The caller checks the campaign's org."""
    database = db if db is not None else get_database()
    runs = database[QUEUED_RUNS]
    roots_query = {"campaign_id": campaign_id, "parent_queued_run_id": None}
    total = runs.count_documents(roots_query)
    roots = list(
        runs.find(roots_query)
        .sort("_id", 1)
        .skip(max(0, offset))
        .limit(max(1, limit))
    )

    chains: dict[str, list[dict[str, Any]]] = {}
    frontier: dict[str, str] = {}  # run id -> its contact's root id
    for root in roots:
        root_id = str(root["queued_run_id"])
        chains[root_id] = [root]
        frontier[root_id] = root_id
    for _ in range(_MAX_RETRY_DEPTH):
        if not frontier:
            break
        children = runs.find(
            {"campaign_id": campaign_id, "parent_queued_run_id": {"$in": list(frontier)}}
        )
        next_frontier: dict[str, str] = {}
        for child in children:
            root_id = frontier[str(child["parent_queued_run_id"])]
            chains[root_id].append(child)
            next_frontier[str(child["queued_run_id"])] = root_id
        frontier = next_frontier

    call_ids = [run["call_id"] for chain in chains.values() for run in chain if run.get("call_id")]
    calls: dict[str, dict[str, Any]] = {}
    if call_ids:
        for call in database[CALL_LOGS].find({"org_id": org_id, "call_id": {"$in": call_ids}}):
            calls[str(call["call_id"])] = call

    return {
        "campaign_id": campaign_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "contacts": [_contact(root, chains[str(root["queued_run_id"])], calls) for root in roots],
    }
