"""Schedule, compute and store ``call_output`` for finished calls.

Lifecycle on the call log (``call_output_status``):

* ``skipped``   the call was not answered: ``call_output`` is the provider's
                output for an unanswered call (``{}`` if it has none).
* ``pending``   due at ``call_output_due_at`` (a short delay after the call
                ends, so the provider's data has landed).
* ``computing`` leased by a worker.
* ``ready``     ``call_output`` is set.
* ``failed``    gave up after ``CALL_OUTPUT_MAX_ATTEMPTS``; ``call_output_error``
                says why. ``POST /calls/{id}/call-output/recompute`` retries.

The ARQ cron ``dispatch_call_outputs`` does the work. The post-call webhook
waits (up to ``CALL_OUTPUT_WEBHOOK_MAX_WAIT_SECONDS``) for a pending output so
the event carries it, as Raya's does.

Answered or not is decided when the output is computed, not when the call
first turns terminal: the telephony hangup can mark a call ``completed``
before the runtime marks it ``answered``. A call already ``skipped`` is
revived if it later turns out to be answered.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pymongo import ReturnDocument

from app.config import settings
from app.database import get_database
from app.services.call_output.base import CallOutputNotReady, get_provider

logger = logging.getLogger(__name__)

CALL_LOGS = "CallLogs"
AGENTS = "Agents"
TERMINAL_STATUSES = frozenset({"completed", "failed"})

PENDING = "pending"
COMPUTING = "computing"
READY = "ready"
FAILED = "failed"
SKIPPED = "skipped"
WAITING_STATES = frozenset({PENDING, COMPUTING})
# Responses that mean the call was not answered and will not become answered.
UNANSWERED = frozenset({"busy", "no_answer", "failed", "cancelled"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def agent_provider_name(agent_doc: dict[str, Any] | None) -> str | None:
    cfg = ((agent_doc or {}).get("config") or {}).get("call_output") or {}
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return None
    name = str(cfg.get("provider") or "").strip()
    return name or None


def unanswered_output(call: dict[str, Any], agent: dict[str, Any] | None) -> dict[str, Any]:
    """The provider's ``call_output`` for a call nobody answered, or ``{}``."""
    try:
        provider = get_provider(agent_provider_name(agent))
        build = getattr(provider, "unanswered_output", None)
        return build(call) if build is not None else {}
    except Exception:
        logger.exception("unanswered_output failed call_id=%s", call.get("call_id"))
        return {}


def schedule_for_call(call_doc: dict[str, Any] | None, *, db: Any = None) -> str | None:
    """Mark a terminal call for ``call_output`` once. Never raises.

    Returns the status set (``pending`` / ``skipped``), or None when nothing
    was scheduled (not terminal, agent not opted in, already scheduled).
    """
    call_id = str((call_doc or {}).get("call_id") or "")
    try:
        if not call_doc or call_doc.get("status") not in TERMINAL_STATUSES:
            return None
        existing = call_doc.get("call_output_status")
        response = call_doc.get("call_response")
        revive = existing == SKIPPED and response == "answered"
        if existing and not revive:
            return None
        database = db if db is not None else get_database()
        agent = database[AGENTS].find_one(
            {"org_id": call_doc.get("org_id"), "agent_id": call_doc.get("agent_id")}
        )
        if not agent_provider_name(agent):
            return None
        now = _now()
        if response in UNANSWERED:
            update = {
                "call_output_status": SKIPPED,
                "call_output": unanswered_output(call_doc, agent),
                "call_output_at": now.isoformat(),
            }
        else:
            # Answered, or not known yet (``pending``): compute_one decides.
            update = {
                "call_output_status": PENDING,
                "call_output_due_at": now + timedelta(seconds=settings.CALL_OUTPUT_DELAY_SECONDS),
                "call_output_attempts": 0,
                "call_output_error": None,
            }
        guard = {"call_output_status": SKIPPED} if revive else {"call_output_status": {"$exists": False}}
        result = database[CALL_LOGS].update_one({"call_id": call_id, **guard}, {"$set": update})
        return update["call_output_status"] if result.modified_count else None
    except Exception:
        logger.exception("Failed to schedule call_output call_id=%s", call_id)
        return None


def claim_due(*, limit: int, db: Any = None, now: datetime | None = None) -> list[dict[str, Any]]:
    database = db if db is not None else get_database()
    current = now or _now()
    lease_until = current + timedelta(seconds=settings.CALL_OUTPUT_LEASE_SECONDS)
    claimed: list[dict[str, Any]] = []
    for _ in range(max(0, limit)):
        doc = database[CALL_LOGS].find_one_and_update(
            {
                "$or": [
                    {"call_output_status": PENDING, "call_output_due_at": {"$lte": current}},
                    {"call_output_status": COMPUTING, "call_output_lease_until": {"$lte": current}},
                ]
            },
            {"$set": {"call_output_status": COMPUTING, "call_output_lease_until": lease_until}},
            sort=[("call_output_due_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if not doc:
            break
        claimed.append(doc)
    return claimed


def _finish(database: Any, call: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    update = {**update, "call_output_lease_until": None, "updated_at": _now().isoformat()}
    doc = database[CALL_LOGS].find_one_and_update(
        {"call_id": call["call_id"]}, {"$set": update}, return_document=ReturnDocument.AFTER
    )
    return doc or {**call, **update}


def _retry_or_fail(database: Any, call: dict[str, Any], error: str) -> dict[str, Any]:
    attempt = int(call.get("call_output_attempts") or 0) + 1
    if attempt < settings.CALL_OUTPUT_MAX_ATTEMPTS:
        logger.info("call_output retry call_id=%s attempt=%s: %s", call["call_id"], attempt, error)
        return _finish(database, call, {
            "call_output_status": PENDING,
            "call_output_attempts": attempt,
            "call_output_error": error,
            "call_output_due_at": _now() + timedelta(seconds=settings.CALL_OUTPUT_RETRY_SECONDS),
        })
    logger.warning("call_output failed call_id=%s after %s attempts: %s", call["call_id"], attempt, error)
    return _finish(database, call, {
        "call_output_status": FAILED,
        "call_output_attempts": attempt,
        "call_output_error": error,
        "call_output_at": _now().isoformat(),
    })


def _skip(database: Any, call: dict[str, Any], note: str | None = None) -> dict[str, Any]:
    agent = database[AGENTS].find_one({"org_id": call.get("org_id"), "agent_id": call.get("agent_id")})
    return _finish(database, call, {
        "call_output_status": SKIPPED,
        "call_output": unanswered_output(call, agent),
        "call_output_error": note,
        "call_output_at": _now().isoformat(),
    })


async def compute_one(call: dict[str, Any], *, client: httpx.AsyncClient, db: Any = None) -> dict[str, Any]:
    database = db if db is not None else get_database()
    response = call.get("call_response")
    if response in UNANSWERED:
        return _skip(database, call)
    if response != "answered":
        # The runtime marks answered calls a moment after the hangup; give it
        # until the attempts run out, then treat the call as not answered.
        attempt = int(call.get("call_output_attempts") or 0) + 1
        if attempt < settings.CALL_OUTPUT_MAX_ATTEMPTS:
            return _retry_or_fail(database, call, f"call_response is {response!r}, not final yet")
        return _skip(database, call, f"call_response stayed {response!r}")
    agent = database[AGENTS].find_one({"org_id": call.get("org_id"), "agent_id": call.get("agent_id")})
    name = agent_provider_name(agent)
    provider = get_provider(name)
    if provider is None:
        return _finish(database, call, {
            "call_output_status": FAILED,
            "call_output_error": f"no call_output provider for this agent ({name!r})",
            "call_output_at": _now().isoformat(),
        })
    try:
        result = await provider.compute(call, agent or {}, client=client)
    except CallOutputNotReady as exc:
        return _retry_or_fail(database, call, f"not ready: {exc}")
    except Exception as exc:  # provider bugs and network errors are retried too
        logger.exception("call_output provider %s failed call_id=%s", name, call.get("call_id"))
        return _retry_or_fail(database, call, f"{type(exc).__name__}: {exc}"[:500])
    return _finish(database, call, {
        "call_output_status": READY,
        "call_output": result.output,
        "call_output_signals": result.signals,
        "call_output_error": None,
        "call_output_at": _now().isoformat(),
        "call_output_attempts": int(call.get("call_output_attempts") or 0) + 1,
    })


async def dispatch_due(*, limit: int | None = None, client: httpx.AsyncClient | None = None,
                       db: Any = None) -> int:
    database = db if db is not None else get_database()
    batch = claim_due(limit=limit or settings.CALL_OUTPUT_DISPATCH_BATCH, db=database)
    if not batch:
        return 0
    owns_client = client is None
    http = client or httpx.AsyncClient()
    try:
        for call in batch:
            try:
                await compute_one(call, client=http, db=database)
            except Exception:
                logger.exception("Unexpected call_output error call_id=%s", call.get("call_id"))
    finally:
        if owns_client:
            await http.aclose()
    return len(batch)


def webhook_should_wait(call: dict[str, Any], agent: dict[str, Any] | None,
                        *, waiting_since: Any, now: datetime | None = None) -> bool:
    """True while the webhook should hold back for this call's ``call_output``."""
    if not agent_provider_name(agent):
        return False
    status = call.get("call_output_status")
    if status is None:
        # Terminal and opted in, but not scheduled yet (e.g. agent opted in
        # after the call ended): don't hold the event for it.
        return False
    if status not in WAITING_STATES:
        return False
    since = _as_utc(waiting_since)
    if since is None:
        return True
    elapsed = ((now or _now()) - since).total_seconds()
    return elapsed < settings.CALL_OUTPUT_WEBHOOK_MAX_WAIT_SECONDS


def recompute(org_id: str, call_id: str, *, db: Any = None) -> dict[str, Any] | None:
    """Queue ``call_output`` to be worked out again now. None if not eligible."""
    database = db if db is not None else get_database()
    call = database[CALL_LOGS].find_one({"org_id": org_id, "call_id": call_id})
    if not call or call.get("status") not in TERMINAL_STATUSES:
        return None
    agent = database[AGENTS].find_one({"org_id": org_id, "agent_id": call.get("agent_id")})
    if not agent_provider_name(agent):
        return None
    if call.get("call_response") != "answered":
        update = {"call_output_status": SKIPPED, "call_output": {}, "call_output_at": _now().isoformat()}
    else:
        update = {"call_output_status": PENDING, "call_output_due_at": _now(),
                  "call_output_attempts": 0, "call_output_error": None,
                  "call_output_lease_until": None}
    return database[CALL_LOGS].find_one_and_update(
        {"org_id": org_id, "call_id": call_id}, {"$set": update},
        return_document=ReturnDocument.AFTER,
    )
