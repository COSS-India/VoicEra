"""FastAPI dependency factories for the unauthenticated-endpoint limits (Layer 1).

Each dependency is a no-op unless ``settings.RATE_LIMIT_ENABLED`` is true, and
each fails open or closed on a Redis outage per ``RATE_LIMIT_FAIL_OPEN`` (a
limiter outage must not take down signup or calls by default — see
rate-limiting-plan.md §10). Every bypass and outage is logged and countable.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status

from app.config import settings
from app.services.limits.counters import counters
from app.services.limits.errors import LimitExceeded
from app.utils.client_ip import ip_in_allowlist, resolve_client_ip, hash_subject

logger = logging.getLogger(__name__)


def _limiter_unavailable(scope: str, exc: Exception) -> None:
    """Apply ``RATE_LIMIT_FAIL_OPEN`` to a Redis error: log and allow, or 503."""
    logger.error("rate_limit.fail_open scope=%s error=%s", scope, exc)
    if not settings.RATE_LIMIT_FAIL_OPEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiter unavailable",
            headers={"Retry-After": "5"},
        ) from exc


async def _enforce_window(*, scope: str, subject_hash: str, limit: int, ttl: int) -> None:
    """Increment the fixed-window counter for (scope, subject_hash) and enforce it.

    Raises ``LimitExceeded`` when the window is over budget. On a Redis error,
    applies ``RATE_LIMIT_FAIL_OPEN``: allow-and-log by default, or a 503 for
    deployments that prefer refusal to unmetered spend.
    """
    key = f"rl:{scope}:{subject_hash}"
    try:
        allowed, count, retry_after = await counters.incr_window(key, limit, ttl)
    except Exception as exc:
        _limiter_unavailable(scope, exc)
        return

    if not allowed:
        logger.info(
            "rate_limit.deny scope=%s subject=%s limit=%s count=%s",
            scope,
            subject_hash,
            limit,
            count,
        )
        raise LimitExceeded(scope=scope, limit=limit, retry_after=retry_after)


async def _peek_window(*, scope: str, subject_hash: str) -> float:
    """Read a usage/window counter without incrementing it."""
    return await counters.get_usage(f"rl:{scope}:{subject_hash}")


def _client_ip_hash(request: Request) -> tuple[str, str]:
    """Return ``(normalised_ip, hash)`` for the request's resolved client IP."""
    normalised = resolve_client_ip(request)
    return normalised, hash_subject(normalised)


def _is_allowlisted(normalised_ip: str) -> bool:
    exempt = ip_in_allowlist(normalised_ip)
    if exempt:
        logger.info("rate_limit.bypass scope=ip reason=allowlist")
    return exempt


async def signup_attempts_guard(request: Request) -> None:
    """Per-IP limit on signup *attempts* — catches probing regardless of outcome."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    normalised, subject_hash = _client_ip_hash(request)
    if _is_allowlisted(normalised):
        return
    await _enforce_window(
        scope="signup_attempts",
        subject_hash=subject_hash,
        limit=settings.SIGNUP_ATTEMPTS_PER_IP_PER_HOUR,
        ttl=3600,
    )


async def signup_success_budget_guard(request: Request) -> None:
    """Reject before doing the work if the IP has already exhausted its
    successful-org-creation budget for the hour or the day.

    Checked separately from ``signup_attempts_guard`` because the resource
    being protected is orgs actually created, not signup attempts — a single
    counter would either let probing run free or let one attacker exhaust the
    daily budget of everyone behind the same NAT (rate-limiting-plan.md §6).
    """
    if not settings.RATE_LIMIT_ENABLED:
        return
    normalised, subject_hash = _client_ip_hash(request)
    if _is_allowlisted(normalised):
        return
    try:
        hourly = await _peek_window(scope="signup_orgs_hour", subject_hash=subject_hash)
        daily = await _peek_window(scope="signup_orgs_day", subject_hash=subject_hash)
    except Exception as exc:
        _limiter_unavailable("signup_orgs", exc)
        return
    if hourly >= settings.SIGNUP_ORGS_PER_IP_PER_HOUR:
        logger.info(
            "rate_limit.deny scope=signup_orgs_hour subject=%s limit=%s count=%s",
            subject_hash,
            settings.SIGNUP_ORGS_PER_IP_PER_HOUR,
            hourly,
        )
        raise LimitExceeded(
            scope="signup_orgs_hour",
            limit=settings.SIGNUP_ORGS_PER_IP_PER_HOUR,
            retry_after=3600,
        )
    if daily >= settings.SIGNUP_ORGS_PER_IP_PER_DAY:
        logger.info(
            "rate_limit.deny scope=signup_orgs_day subject=%s limit=%s count=%s",
            subject_hash,
            settings.SIGNUP_ORGS_PER_IP_PER_DAY,
            daily,
        )
        raise LimitExceeded(
            scope="signup_orgs_day",
            limit=settings.SIGNUP_ORGS_PER_IP_PER_DAY,
            retry_after=86400,
        )


async def record_signup_success(request: Request) -> None:
    """Increment the success counters. Call after the org is actually created."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    normalised, subject_hash = _client_ip_hash(request)
    if ip_in_allowlist(normalised):
        return
    try:
        await counters.incr_window(
            f"rl:signup_orgs_hour:{subject_hash}",
            settings.SIGNUP_ORGS_PER_IP_PER_HOUR,
            3600,
        )
        await counters.incr_window(
            f"rl:signup_orgs_day:{subject_hash}",
            settings.SIGNUP_ORGS_PER_IP_PER_DAY,
            86400,
        )
    except Exception as exc:
        # Accounting is not on the critical path — a missed success counter
        # only widens a budget slightly, it never breaks signup.
        logger.error("rate_limit.fail_open scope=signup_orgs error=%s", exc)


async def auth_attempts_guard(request: Request) -> None:
    """Per-IP limit shared by /login, /forgot-password, /reset-password."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    normalised, subject_hash = _client_ip_hash(request)
    if _is_allowlisted(normalised):
        return
    await _enforce_window(
        scope="auth_attempts",
        subject_hash=subject_hash,
        limit=settings.AUTH_ATTEMPTS_PER_IP_PER_MINUTE,
        ttl=60,
    )


async def check_user_join_guard(request: Request) -> None:
    """Per-IP limit for the unauthenticated /users/check/{email} enumeration
    surface (S9). Reuses the auth-attempts budget rather than adding a new
    knob — this endpoint is the same class of probing risk."""
    await auth_attempts_guard(request)


def reset_mail_subject_hash(email: str) -> str:
    """Reset-mail limiting is keyed on the *target* email, not the requester's
    IP — otherwise a distributed requester can mail-bomb one victim while
    staying under every per-IP limit (rate-limiting-plan.md §6)."""
    return hash_subject(email.strip().lower())


async def reset_mail_guard(email: str) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    subject_hash = reset_mail_subject_hash(email)
    await _enforce_window(
        scope="reset_mail",
        subject_hash=subject_hash,
        limit=settings.RESET_MAILS_PER_EMAIL_PER_HOUR,
        ttl=3600,
    )
