"""Post-call webhooks: one signed POST per finished call to the agent's URL.

Outbox pattern. When a call log reaches a terminal status (``completed`` or
``failed``), :func:`schedule_for_call` upserts one row per call into
``CallWebhookDeliveries``, so patching the same call again never schedules a
second delivery. The ARQ worker's ``dispatch_call_webhooks`` cron claims due
rows, re-reads the call log (so transcript and recording patches that land
after the hangup are included), signs the body and POSTs it. Failures are
retried with exponential backoff up to ``CALL_WEBHOOK_MAX_ATTEMPTS``.

Signature (``X-VoicEra-Signature: v1=<hex>``)::

    hex = HMAC_SHA256(secret, f"{X-VoicEra-Timestamp}.{raw_body}")

Receivers should recompute it over the raw body, compare in constant time,
and reject timestamps older than a few minutes. :func:`verify_signature` is
the reference implementation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pymongo import ReturnDocument

from app.config import settings
from app.database import get_database
from app.services.secret_crypto import decrypt_json, encrypt_json

logger = logging.getLogger(__name__)

COLLECTION = "CallWebhookDeliveries"
AGENTS = "Agents"
CALL_LOGS = "CallLogs"

EVENT_CALL_ENDED = "call.ended"
TERMINAL_STATUSES = frozenset({"completed", "failed"})
SECRET_PREFIX = "whsec_"
USER_AGENT = "VoicEra-Webhooks/1"

STATE_PENDING = "pending"
STATE_IN_FLIGHT = "in_flight"
STATE_DELIVERED = "delivered"
STATE_FAILED = "failed"

# Call-log fields sent in ``data``. Storage URLs are internal (MinIO), so the
# payload carries API paths for the transcript and recording instead.
_PAYLOAD_FIELDS = (
    "call_id",
    "org_id",
    "agent_id",
    "agent_name",
    "call_type",
    "status",
    "call_response",
    "from_number",
    "to_number",
    "telephony_provider",
    "provider_call_sid",
    "custom_variables",
    "campaign_id",
    "campaign_name",
    "queued_run_id",
    "start_time_utc",
    "end_time_utc",
    "duration",
    "error_message",
    "created_at",
)


class AgentWebhookNotFoundError(LookupError):
    """Raised when the agent for a webhook operation does not exist."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    """pymongo returns naive UTC datetimes; make them comparable."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Secrets and signatures
# ---------------------------------------------------------------------------


def generate_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def rotate_agent_secret(org_id: str, agent_id: str, *, db: Any = None) -> str:
    """Create or replace the agent's signing secret and return it in plain text.

    The secret is stored encrypted and is only ever returned by this call.
    """
    database = db if db is not None else get_database()
    secret = generate_secret()
    result = database[AGENTS].update_one(
        {"org_id": org_id, "agent_id": agent_id},
        {
            "$set": {
                "webhook_secret": encrypt_json({"secret": secret}),
                "webhook_secret_rotated_at": _now().isoformat(),
            }
        },
    )
    if result.matched_count == 0:
        raise AgentWebhookNotFoundError(agent_id)
    logger.info("Webhook secret rotated agent=%s org=%s", agent_id, org_id)
    return secret


def agent_secret(agent_doc: dict[str, Any] | None) -> str | None:
    blob = (agent_doc or {}).get("webhook_secret")
    if not blob:
        return None
    try:
        return str(decrypt_json(blob).get("secret") or "") or None
    except Exception:
        logger.exception("Could not decrypt webhook secret for agent=%s", (agent_doc or {}).get("agent_id"))
        return None


def sign(secret: str, timestamp: int, body: bytes) -> str:
    message = f"{timestamp}.".encode("utf-8") + body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"v1={digest}"


def verify_signature(
    secret: str,
    timestamp: str | int,
    body: bytes,
    signature: str,
    *,
    tolerance_seconds: int = 300,
    now: datetime | None = None,
) -> bool:
    """Reference check for receivers: right signature and a recent timestamp."""
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = int((now or _now()).timestamp())
    if abs(current - ts) > tolerance_seconds:
        return False
    return hmac.compare_digest(sign(secret, ts, body), str(signature or ""))


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def webhook_target(agent_doc: dict[str, Any] | None) -> str | None:
    """Return the agent's webhook URL when the webhook is enabled."""
    webhook = ((agent_doc or {}).get("config") or {}).get("webhook") or {}
    if not isinstance(webhook, dict) or not webhook.get("enabled"):
        return None
    url = str(webhook.get("url") or "").strip()
    return url or None


def schedule_for_call(
    call_doc: dict[str, Any] | None,
    *,
    db: Any = None,
    settle_seconds: int | None = None,
) -> bool:
    """Queue the post-call webhook for a terminal call. Never raises.

    Returns True when a delivery row exists for the call after this call
    (newly created or already there), False otherwise.
    """
    call_id = str((call_doc or {}).get("call_id") or "")
    try:
        if not call_doc or call_doc.get("status") not in TERMINAL_STATUSES:
            return False
        org_id = str(call_doc.get("org_id") or "")
        agent_id = str(call_doc.get("agent_id") or "")
        if not (call_id and org_id and agent_id):
            return False

        database = db if db is not None else get_database()
        agent = database[AGENTS].find_one({"org_id": org_id, "agent_id": agent_id})
        url = webhook_target(agent)
        if not url:
            return False

        now = _now()
        settle = settings.CALL_WEBHOOK_SETTLE_SECONDS if settle_seconds is None else settle_seconds
        database[COLLECTION].update_one(
            {"call_id": call_id},
            {
                "$setOnInsert": {
                    "call_id": call_id,
                    "org_id": org_id,
                    "agent_id": agent_id,
                    "event": EVENT_CALL_ENDED,
                    "url": url,
                    "state": STATE_PENDING,
                    "attempts": 0,
                    "next_attempt_at": now + timedelta(seconds=max(0, settle)),
                    "created_at": now,
                    "updated_at": now,
                }
            },
            upsert=True,
        )
        return True
    except Exception:
        logger.exception("Failed to schedule call webhook call_id=%s", call_id)
        return False


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def _load_transcript_turns(call_doc: dict[str, Any]) -> list[dict[str, Any]] | None:
    from app.services.call_transcript_service import try_load_turns

    if not call_doc.get("transcript_url"):
        return None
    return try_load_turns(call_doc)


def build_payload(
    call_doc: dict[str, Any],
    *,
    attempt: int,
    sent_at: datetime,
    transcript: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    data = {field: call_doc.get(field) for field in _PAYLOAD_FIELDS}
    # Turn-by-turn transcript, or null when there is none (unanswered call,
    # or storage unreachable: the transcript_path still works later).
    data["transcript"] = transcript
    call_id = str(call_doc.get("call_id") or "")
    base = f"{settings.API_V1_PREFIX}/calls/{call_id}"
    has_recording = bool(call_doc.get("recording_url") or call_doc.get("provider_recording_url"))
    data["artifacts"] = {
        "transcript_path": f"{base}/transcript" if call_doc.get("transcript_url") else None,
        "recording_path": f"{base}/recording" if has_recording else None,
        "metrics_path": f"{base}/metrics",
    }
    return {
        "event": EVENT_CALL_ENDED,
        "delivery_id": call_id,
        "attempt": attempt,
        "sent_at": sent_at.isoformat(),
        "data": data,
    }


def backoff_seconds(attempt: int) -> int:
    """Delay before the next try after ``attempt`` failed (1-based)."""
    base = max(1, settings.CALL_WEBHOOK_BACKOFF_BASE_SECONDS)
    return int(min(base * (2 ** max(0, attempt - 1)), settings.CALL_WEBHOOK_BACKOFF_MAX_SECONDS))


def _finish(
    database: Any,
    delivery: dict[str, Any],
    *,
    attempt: int,
    ok: bool,
    status_code: int | None,
    error: str | None,
    retry: bool = True,
) -> dict[str, Any]:
    now = _now()
    update: dict[str, Any] = {
        "attempts": attempt,
        "last_attempt_at": now,
        "last_status_code": status_code,
        "last_error": error,
        "lease_until": None,
        "updated_at": now,
    }
    if ok:
        update.update(state=STATE_DELIVERED, delivered_at=now, next_attempt_at=None)
    elif retry and attempt < settings.CALL_WEBHOOK_MAX_ATTEMPTS:
        update.update(state=STATE_PENDING, next_attempt_at=now + timedelta(seconds=backoff_seconds(attempt)))
    else:
        update.update(state=STATE_FAILED, next_attempt_at=None)
    doc = database[COLLECTION].find_one_and_update(
        {"call_id": delivery["call_id"]},
        {"$set": update},
        return_document=ReturnDocument.AFTER,
    )
    level = logging.INFO if ok else logging.WARNING
    logger.log(
        level,
        "Call webhook call_id=%s attempt=%s state=%s status=%s error=%s",
        delivery["call_id"],
        attempt,
        update["state"],
        status_code,
        error,
    )
    return doc or {**delivery, **update}


async def deliver(
    delivery: dict[str, Any],
    *,
    client: httpx.AsyncClient,
    db: Any = None,
) -> dict[str, Any]:
    """Send one delivery and record the outcome. Returns the updated row."""
    database = db if db is not None else get_database()
    attempt = int(delivery.get("attempts") or 0) + 1
    org_id = delivery.get("org_id")

    call = database[CALL_LOGS].find_one({"org_id": org_id, "call_id": delivery["call_id"]})
    if not call:
        return _finish(database, delivery, attempt=attempt, ok=False, status_code=None,
                       error="call log not found", retry=False)

    agent = database[AGENTS].find_one({"org_id": org_id, "agent_id": delivery.get("agent_id")})
    url = webhook_target(agent)
    if not url:
        return _finish(database, delivery, attempt=attempt, ok=False, status_code=None,
                       error="webhook disabled on the agent", retry=False)
    secret = agent_secret(agent)
    if not secret:
        return _finish(database, delivery, attempt=attempt, ok=False, status_code=None,
                       error="agent has no webhook signing secret; rotate one first")

    sent_at = _now()
    payload = build_payload(
        call,
        attempt=attempt,
        sent_at=sent_at,
        transcript=_load_transcript_turns(call),
    )
    body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    timestamp = int(sent_at.timestamp())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-VoicEra-Event": EVENT_CALL_ENDED,
        "X-VoicEra-Delivery": str(delivery["call_id"]),
        "X-VoicEra-Attempt": str(attempt),
        "X-VoicEra-Timestamp": str(timestamp),
        "X-VoicEra-Signature": sign(secret, timestamp, body),
    }
    try:
        response = await client.post(
            url,
            content=body,
            headers=headers,
            timeout=settings.CALL_WEBHOOK_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return _finish(database, delivery, attempt=attempt, ok=False, status_code=None,
                       error=f"{type(exc).__name__}: {exc}"[:500])

    if 200 <= response.status_code < 300:
        return _finish(database, delivery, attempt=attempt, ok=True,
                       status_code=response.status_code, error=None)
    return _finish(database, delivery, attempt=attempt, ok=False,
                   status_code=response.status_code, error=f"HTTP {response.status_code}")


def claim_due(*, limit: int, db: Any = None, now: datetime | None = None) -> list[dict[str, Any]]:
    """Atomically lease up to ``limit`` due deliveries (stale leases included)."""
    database = db if db is not None else get_database()
    current = now or _now()
    lease_until = current + timedelta(seconds=settings.CALL_WEBHOOK_LEASE_SECONDS)
    claimed: list[dict[str, Any]] = []
    for _ in range(max(0, limit)):
        doc = database[COLLECTION].find_one_and_update(
            {
                "$or": [
                    {"state": STATE_PENDING, "next_attempt_at": {"$lte": current}},
                    {"state": STATE_IN_FLIGHT, "lease_until": {"$lte": current}},
                ]
            },
            {"$set": {"state": STATE_IN_FLIGHT, "lease_until": lease_until, "updated_at": current}},
            sort=[("next_attempt_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if not doc:
            break
        claimed.append(doc)
    return claimed


async def dispatch_due(
    *,
    limit: int | None = None,
    client: httpx.AsyncClient | None = None,
    db: Any = None,
) -> int:
    """Deliver every due webhook (up to ``limit``). Returns how many were tried."""
    database = db if db is not None else get_database()
    batch = claim_due(limit=limit or settings.CALL_WEBHOOK_DISPATCH_BATCH, db=database)
    if not batch:
        return 0
    owns_client = client is None
    http = client or httpx.AsyncClient(follow_redirects=False)
    try:
        for delivery in batch:
            try:
                await deliver(delivery, client=http, db=database)
            except Exception:
                logger.exception("Unexpected error delivering call webhook call_id=%s", delivery.get("call_id"))
    finally:
        if owns_client:
            await http.aclose()
    return len(batch)


# ---------------------------------------------------------------------------
# Read / redeliver (API)
# ---------------------------------------------------------------------------


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    return value


def to_response(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    keys = (
        "call_id", "agent_id", "event", "url", "state", "attempts", "last_status_code",
        "last_error", "next_attempt_at", "last_attempt_at", "delivered_at", "created_at",
    )
    return {key: _iso(doc.get(key)) for key in keys}


def get_delivery(org_id: str, call_id: str, *, db: Any = None) -> dict[str, Any] | None:
    database = db if db is not None else get_database()
    return to_response(database[COLLECTION].find_one({"org_id": org_id, "call_id": call_id}))


def redeliver(org_id: str, call_id: str, *, db: Any = None) -> dict[str, Any] | None:
    """Queue a fresh delivery now. Returns the row, or None when not eligible."""
    database = db if db is not None else get_database()
    now = _now()
    doc = database[COLLECTION].find_one_and_update(
        {"org_id": org_id, "call_id": call_id},
        {"$set": {"state": STATE_PENDING, "attempts": 0, "next_attempt_at": now,
                  "lease_until": None, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if doc:
        return to_response(doc)
    call = database[CALL_LOGS].find_one({"org_id": org_id, "call_id": call_id})
    if schedule_for_call(call, db=database, settle_seconds=0):
        return get_delivery(org_id, call_id, db=database)
    return None


__all__ = [
    "AgentWebhookNotFoundError",
    "EVENT_CALL_ENDED",
    "agent_secret",
    "backoff_seconds",
    "build_payload",
    "claim_due",
    "deliver",
    "dispatch_due",
    "generate_secret",
    "get_delivery",
    "redeliver",
    "rotate_agent_secret",
    "schedule_for_call",
    "sign",
    "verify_signature",
    "webhook_target",
]
