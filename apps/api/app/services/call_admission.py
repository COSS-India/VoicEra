"""Unified call admission funnel for ad-hoc outbound, inbound, and web calls.

Closes G1 in docs/developer/rate-limiting-plan.md: today, org concurrency
slots are acquired only by the campaign dispatcher
(``campaign_call_dispatcher.py``); ad-hoc calls placed through
``POST /calls/{outbound,inbound,web}`` bypass every limit. This module adds
that check at the router layer, additively — it does not change the
signature or behaviour of ``outbound_call_service`` /
``inbound_call_service`` / ``web_call_service``, and it is a complete no-op
while ``RATE_LIMIT_ENABLED=false`` (the current default), matching the
Layer 0/1 pattern.

Explicitly deferred (see conversation / rollout plan):

- **Layer 2b** (signed WebSocket admission token) is not implemented here.
  Without it, a denied web call can still be joined by the runtime's
  existing self-mint fallback in ``apps/runtime/routes/agent.py`` — this
  layer protects the ad-hoc REST admission path, not that fallback.
- **Layer 4** (usage accounting) is not implemented here. The org daily
  quota check below reads ``usage:dur:{org_id}:{YYYYMMDD}``, which nothing
  increments yet — so the quota is real but currently always sees zero
  consumption. Org *concurrency* is fully enforced by this layer on its own.
- Per-IP concurrency is skipped for telephony (`inbound`) and campaign
  calls: the apparent request origin there is a provider webhook or the
  runtime, not a real client address.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from fastapi import Request

from app.config import settings
from app.services.call_concurrency.service import (
    CallConcurrencyLimitError,
    CallConcurrencySlot,
    call_concurrency,
)
from app.services.limits.counters import counters, usage_key
from app.services.limits.policy import get_org_daily_call_seconds
from app.utils.client_ip import (
    hash_subject,
    ip_in_allowlist,
    is_internal_service_subject,
    resolve_client_ip,
)

logger = logging.getLogger(__name__)

CallKind = Literal["outbound", "inbound", "web"]

# A call starting with less than this much daily budget left is refused
# outright — starting a call that dies a few seconds later is worse than a
# clean refusal (rate-limiting-plan.md §9, Layer 2).
_MIN_REMAINING_SECONDS = 30


class CallAdmissionError(Exception):
    """Raised when admission denies a call. Mapped to HTTP 429 by the router."""

    def __init__(self, *, reason: str, message: str, retry_after: int = 5) -> None:
        self.reason = reason
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)


@dataclass
class AdmittedCall:
    """What Layer 2 hands back to the router: the slot to bind once the
    CallLog exists, or release if registration fails afterwards."""

    slot: CallConcurrencySlot | None


async def _check_org_daily_quota(org_id: str) -> None:
    limit = await get_org_daily_call_seconds(org_id)
    if limit <= 0:
        return  # 0 means "no quota configured", not "zero budget"
    try:
        consumed = await counters.get_usage(usage_key(org_id))
    except Exception as exc:
        # Accounting/quota reads are not allowed to take calls down — see
        # RATE_LIMIT_FAIL_OPEN in Layer 0/1. A read failure here behaves as
        # RATE_LIMIT_FAIL_OPEN=true unconditionally: never block a call
        # because the usage counter was unreachable.
        logger.error("rate_limit.fail_open scope=org_daily_quota error=%s", exc)
        return
    remaining = limit - consumed
    if remaining < _MIN_REMAINING_SECONDS:
        logger.info(
            "call_admission.reject reason=quota org_id=%s remaining=%.0f",
            org_id,
            remaining,
        )
        raise CallAdmissionError(
            reason="quota",
            message="Daily call-seconds quota exhausted for this organisation",
            retry_after=60,
        )


def _per_ip_scope(
    *, call_kind: CallKind, request: Request | None, current_user_email: str | None
) -> tuple[str | None, int | None]:
    """Return (scope_key, scope_max_concurrent) for per-IP concurrency, or
    (None, None) when it does not apply — telephony/inbound has no real
    client IP, and an exempt caller skips per-IP concurrency only (never the
    org-scoped checks above), per rate-limiting-plan.md §8."""
    if call_kind != "web" or request is None:
        return None, None

    if is_internal_service_subject(current_user_email):
        logger.info("rate_limit.bypass scope=ip reason=internal")
        return None, None

    normalised_ip = resolve_client_ip(request)
    if ip_in_allowlist(normalised_ip):
        logger.info("rate_limit.bypass scope=ip reason=allowlist")
        return None, None

    scope_key = f"ip:{hash_subject(normalised_ip)}"
    return scope_key, settings.MAX_CONCURRENT_CALLS_PER_IP


async def admit_call(
    *,
    org_id: str,
    call_kind: CallKind,
    request: Request | None = None,
    current_user_email: str | None = None,
) -> AdmittedCall:
    """Check quota + concurrency for an ad-hoc call and reserve a slot.

    Raises ``CallAdmissionError`` on denial. On success, the caller must
    eventually call ``bind_admitted_call`` (once the CallLog's ``call_id``
    exists) or ``release_admitted_call`` (if registration fails first) — the
    same reserve/bind/release shape the campaign dispatcher already uses.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return AdmittedCall(slot=None)

    await _check_org_daily_quota(org_id)

    scope_key, scope_max_concurrent = _per_ip_scope(
        call_kind=call_kind, request=request, current_user_email=current_user_email
    )

    try:
        slot = await call_concurrency.acquire_org_slot(
            org_id,
            source=f"call_admission:{call_kind}",
            timeout=0,
            scope_key=scope_key,
            scope_max_concurrent=scope_max_concurrent,
        )
    except CallConcurrencyLimitError as exc:
        # try_acquire_concurrent_slot_details returns a bare rejection
        # whether the org limit or the scope (per-IP) limit tripped, so the
        # two can't be told apart here without an extra read; log the
        # coarser "concurrency" reason rather than guess.
        reason = "concurrency_ip" if scope_key else "concurrency_org"
        logger.info(
            "call_admission.reject reason=%s org_id=%s limit=%s",
            reason,
            org_id,
            exc.max_concurrent,
        )
        raise CallAdmissionError(
            reason=reason,
            message="Concurrent call limit reached",
            retry_after=5,
        ) from exc

    return AdmittedCall(slot=slot)


async def bind_admitted_call(admitted: AdmittedCall, call_id: str) -> None:
    """Bind the reserved slot to ``call_id`` so the existing hangup path
    (``release_call_slot``) frees it. No-op when admission was skipped
    (``RATE_LIMIT_ENABLED=false`` or Layer 2b/legacy campaign paths)."""
    if admitted.slot is None:
        return
    await call_concurrency.bind_call_slot(admitted.slot, call_id)


async def release_admitted_call(admitted: AdmittedCall) -> None:
    """Roll back a reserved-but-unbound slot when registration fails after
    admission succeeded — mirrors the rollback pattern in
    ``campaign_call_dispatcher.py``."""
    if admitted.slot is None:
        return
    await call_concurrency.release_slot(admitted.slot)
