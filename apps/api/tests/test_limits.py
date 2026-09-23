"""Tests for app.services.limits and app.utils.client_ip.

Runs against a real Redis instance rather than a fake client — the behaviour
under test is the Lua scripts themselves (S3, S3b, S4) plus Redis 7 features
(``EXPIRE ... NX``), which a mocked client would not exercise and an older
Redis would not support. Point ``RTK_TEST_REDIS_URL`` at a scratch instance;
defaults to db 15 of the docker-compose Redis (``redis:7``), which is
otherwise reserved for ARQ/db 0 — tests only ever touch db 15 and flush only
that db.
"""

from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from fastapi import HTTPException, Request

from app.config import settings
from app.services.call_concurrency.rate_limiter import RateLimiter
from app.services.limits import deps
from app.services.limits.counters import _Counters
from app.services.limits.errors import LimitExceeded
from app.utils import client_ip

TEST_REDIS_URL = os.environ.get(
    "RTK_TEST_REDIS_URL", "redis://:redissecret@localhost:6379/15"
)


def _make_request(
    client_host: str = "203.0.113.5",
    headers: dict[str, str] | None = None,
) -> Request:
    scope = {
        "type": "http",
        "client": (client_host, 12345),
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
    }
    return Request(scope)


@pytest_asyncio.fixture(autouse=True)
async def _clean_redis():
    """Flush the scratch Redis DB before and after each test."""
    client = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
    await client.flushdb()
    yield
    await client.flushdb()
    await client.aclose()


@pytest.fixture(autouse=True)
def _limit_settings(monkeypatch):
    """Point the shared settings singleton at the scratch Redis and a known salt.

    Also resets the process-global ``counters`` singleton's cached client
    before each test: pytest-asyncio gives each test its own event loop, but
    ``counters`` is constructed once per process (correct in production,
    where uvicorn runs a single long-lived loop) — reusing a client bound to
    a previous test's already-closed loop causes silent cross-test failures.
    """
    monkeypatch.setattr(settings, "REDIS_URL", TEST_REDIS_URL)
    monkeypatch.setattr(settings, "RATE_LIMIT_IP_SALT", "test-salt")
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", True)
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
    monkeypatch.setattr(settings, "RATE_LIMIT_IP_ALLOWLIST", "")
    monkeypatch.setattr(deps.counters, "_client", None)
    monkeypatch.setattr(deps.counters, "_incr_sha", None)
    monkeypatch.setattr(deps.counters, "_claim_sha", None)
    yield


@pytest.fixture
def counters(_limit_settings):
    """A fresh _Counters instance per test, wired to the scratch Redis."""
    c = _Counters()
    return c


# ---------------------------------------------------------------------------
# counters.incr_window — fixed window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_incr_window_allows_up_to_limit(counters):
    for _ in range(3):
        allowed, count, _ = await counters.incr_window("k:a", limit=3, ttl=60)
        assert allowed
    allowed, count, retry_after = await counters.incr_window("k:a", limit=3, ttl=60)
    assert not allowed
    assert count == 4
    assert retry_after > 0


@pytest.mark.asyncio
async def test_incr_window_expires_rather_than_accumulating(counters):
    allowed, count, _ = await counters.incr_window("k:b", limit=1, ttl=1)
    assert allowed and count == 1
    denied, _, _ = await counters.incr_window("k:b", limit=1, ttl=1)
    assert not denied
    time.sleep(1.2)
    allowed_again, count_again, _ = await counters.incr_window("k:b", limit=1, ttl=1)
    assert allowed_again
    assert count_again == 1  # counter reset, not accumulated


@pytest.mark.asyncio
async def test_claim_once_is_single_use(counters):
    first = await counters.claim_once("nonce:1", ttl=60)
    second = await counters.claim_once("nonce:1", ttl=60)
    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_add_usage_accumulates_and_get_usage_reads_it(counters):
    await counters.add_usage("usage:org1", 30, ttl=60)
    await counters.add_usage("usage:org1", 45, ttl=60)
    assert await counters.get_usage("usage:org1") == 75.0


@pytest.mark.asyncio
async def test_get_usage_missing_key_is_zero(counters):
    assert await counters.get_usage("usage:missing") == 0.0


# ---------------------------------------------------------------------------
# client_ip — X-Forwarded-For parsing, IPv6 /64, allowlist
# ---------------------------------------------------------------------------


def test_no_trust_uses_request_client_ignoring_xff(monkeypatch):
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
    req = _make_request("198.51.100.9", {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"})
    assert client_ip.resolve_client_ip(req) == "198.51.100.9"


def test_trust_with_one_hop_takes_rightmost(monkeypatch):
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
    # nginx appends: leftmost is attacker-supplied, rightmost is the real hop.
    req = _make_request("10.0.0.1", {"X-Forwarded-For": "203.0.113.1, 10.0.0.5"})
    assert client_ip.resolve_client_ip(req) == "10.0.0.5"


def test_trust_with_two_hops_takes_second_from_right(monkeypatch):
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 2)
    req = _make_request(
        "10.0.0.1", {"X-Forwarded-For": "203.0.113.1, 198.51.100.2, 10.0.0.5"}
    )
    assert client_ip.resolve_client_ip(req) == "198.51.100.2"


def test_short_chain_falls_back_to_rightmost_not_leftmost(monkeypatch):
    """A chain shorter than TRUSTED_PROXY_HOPS means the hop count is wrong or
    a proxy dropped the header. Falling back to hops[0] there would let a
    client pick its own subject by sending a single-entry header — so the
    fallback must be the rightmost (nearest trusted proxy) entry instead."""
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 3)
    req = _make_request("10.0.0.1", {"X-Forwarded-For": "203.0.113.1, 10.0.0.5"})
    assert client_ip.resolve_client_ip(req) == "10.0.0.5"


def test_zero_hops_never_resolves_to_the_leftmost_entry(monkeypatch):
    """TRUSTED_PROXY_HOPS=0 is a misconfiguration; it must not degrade into
    trusting the client-supplied leftmost entry."""
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 0)
    req = _make_request("10.0.0.1", {"X-Forwarded-For": "203.0.113.1, 10.0.0.5"})
    assert client_ip.resolve_client_ip(req) == "10.0.0.5"


def test_ipv6_addresses_in_one_64_share_a_subject(monkeypatch):
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
    req_a = _make_request("2001:db8:1234:5678::1")
    req_b = _make_request("2001:db8:1234:5678:aaaa:bbbb::2")
    normalised_a = client_ip.resolve_client_ip(req_a)
    normalised_b = client_ip.resolve_client_ip(req_b)
    assert normalised_a == normalised_b == "2001:db8:1234:5678::"


def test_hash_subject_never_contains_raw_ip():
    hashed = client_ip.hash_subject("203.0.113.5")
    assert "203.0.113.5" not in hashed
    assert len(hashed) == 16


def test_allowlist_matches_exact_cidr_and_v6_prefix(monkeypatch):
    monkeypatch.setattr(
        settings,
        "RATE_LIMIT_IP_ALLOWLIST",
        "203.0.113.7,198.51.100.0/24,2001:db8::/32",
    )
    client_ip._parsed_allowlist.cache_clear()
    assert client_ip.ip_in_allowlist("203.0.113.7")
    assert client_ip.ip_in_allowlist("198.51.100.42")
    assert client_ip.ip_in_allowlist("2001:db8:1234::")
    assert not client_ip.ip_in_allowlist("203.0.113.8")
    assert not client_ip.ip_in_allowlist("2001:db9::")


def test_is_internal_service_subject():
    assert client_ip.is_internal_service_subject("bot@voicera.internal")
    assert not client_ip.is_internal_service_subject("someone@example.com")
    assert not client_ip.is_internal_service_subject(None)


# ---------------------------------------------------------------------------
# config validators — malformed allowlist aborts startup
# ---------------------------------------------------------------------------


def test_malformed_allowlist_entry_rejected_at_settings_load():
    from app.config import Settings

    with pytest.raises(Exception):
        Settings(RATE_LIMIT_IP_ALLOWLIST="not-a-cidr")


def test_rate_limit_enabled_requires_ip_salt():
    from app.config import Settings

    with pytest.raises(Exception):
        Settings(RATE_LIMIT_ENABLED=True, RATE_LIMIT_IP_SALT="")


# ---------------------------------------------------------------------------
# deps — fail-open / fail-closed, allowlist bypass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signup_attempts_guard_enforces_hourly_limit(monkeypatch):
    monkeypatch.setattr(settings, "SIGNUP_ATTEMPTS_PER_IP_PER_HOUR", 2)
    req = _make_request("203.0.113.50")
    await deps.signup_attempts_guard(req)
    await deps.signup_attempts_guard(req)
    with pytest.raises(LimitExceeded) as exc_info:
        await deps.signup_attempts_guard(req)
    assert exc_info.value.scope == "signup_attempts"


@pytest.mark.asyncio
async def test_signup_success_budget_guard_honours_fail_open(monkeypatch):
    monkeypatch.setattr(
        deps.counters, "get_usage", AsyncMock(side_effect=ConnectionError("redis down"))
    )
    req = _make_request("203.0.113.51")
    await deps.signup_success_budget_guard(req)  # fail-open: allowed

    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", False)
    with pytest.raises(HTTPException) as exc_info:
        await deps.signup_success_budget_guard(req)
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_allowlisted_ip_skips_auth_attempts_guard(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ATTEMPTS_PER_IP_PER_MINUTE", 1)
    monkeypatch.setattr(settings, "RATE_LIMIT_IP_ALLOWLIST", "203.0.113.99")
    client_ip._parsed_allowlist.cache_clear()
    req = _make_request("203.0.113.99")
    for _ in range(5):
        await deps.auth_attempts_guard(req)  # never raises


@pytest.mark.asyncio
async def test_reset_mail_guard_keys_on_email_not_ip(monkeypatch):
    monkeypatch.setattr(settings, "RESET_MAILS_PER_EMAIL_PER_HOUR", 1)
    await deps.reset_mail_guard("victim@example.com")
    with pytest.raises(LimitExceeded):
        await deps.reset_mail_guard("victim@example.com")
    # A different address is a different counter.
    await deps.reset_mail_guard("other@example.com")


@pytest.mark.asyncio
async def test_disabled_rate_limiting_is_a_no_op(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(settings, "SIGNUP_ATTEMPTS_PER_IP_PER_HOUR", 1)
    req = _make_request("203.0.113.60")
    for _ in range(5):
        await deps.signup_attempts_guard(req)  # never raises while disabled


@pytest.mark.asyncio
async def test_fail_open_allows_on_redis_error(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", True)

    async def _raise(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(deps.counters, "incr_window", _raise)
    # Must not raise LimitExceeded or HTTPException.
    await deps._enforce_window(scope="x", subject_hash="h", limit=1, ttl=60)


@pytest.mark.asyncio
async def test_fail_closed_returns_503_on_redis_error(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", False)

    async def _raise(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(deps.counters, "incr_window", _raise)
    with pytest.raises(HTTPException) as exc_info:
        await deps._enforce_window(scope="x", subject_hash="h", limit=1, ttl=60)
    assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# rate_limiter — S3/S3b stale-timeout derivation, S4 unique members,
# per-IP concurrency via scope_key
# ---------------------------------------------------------------------------


def test_stale_call_timeout_is_derived_from_duration_ceiling(monkeypatch):
    monkeypatch.setattr(settings, "MAX_CALL_DURATION_CEILING_SECONDS", 1800)
    limiter = RateLimiter()
    assert limiter.stale_call_timeout == 1800 + 300


def test_stale_call_timeout_has_a_floor(monkeypatch):
    monkeypatch.setattr(settings, "MAX_CALL_DURATION_CEILING_SECONDS", 60)
    limiter = RateLimiter()
    assert limiter.stale_call_timeout == 1200


def test_scope_stale_timeout_is_independent_and_shorter(monkeypatch):
    monkeypatch.setattr(settings, "MAX_CALL_DURATION_CEILING_SECONDS", 1800)
    monkeypatch.setattr(settings, "RATE_LIMIT_SCOPE_STALE_SECONDS", 900)
    limiter = RateLimiter()
    assert limiter.scope_stale_call_timeout == 900
    assert limiter.scope_stale_call_timeout < limiter.stale_call_timeout


@pytest.mark.asyncio
async def test_acquire_token_unique_members_do_not_collide(monkeypatch):
    """S4: two acquisitions must not share a ZADD member even if `time.time()`
    happens to return the same float for both."""
    monkeypatch.setattr(settings, "REDIS_URL", TEST_REDIS_URL)
    limiter = RateLimiter()
    frozen_time = time.time()
    monkeypatch.setattr(time, "time", lambda: frozen_time)
    first = await limiter.acquire_token("org-collide", rate_limit=2)
    second = await limiter.acquire_token("org-collide", rate_limit=2)
    third = await limiter.acquire_token("org-collide", rate_limit=2)
    assert first and second
    assert not third  # limit of 2 correctly enforced despite identical timestamps


@pytest.mark.asyncio
async def test_per_ip_concurrency_uses_independent_scope_reaper(monkeypatch):
    """A leaked per-IP slot must be reaped on RATE_LIMIT_SCOPE_STALE_SECONDS,
    not on the org's much longer stale_call_timeout (S3b)."""
    monkeypatch.setattr(settings, "REDIS_URL", TEST_REDIS_URL)
    monkeypatch.setattr(settings, "RATE_LIMIT_SCOPE_STALE_SECONDS", 1)
    monkeypatch.setattr(settings, "MAX_CALL_DURATION_CEILING_SECONDS", 1800)
    limiter = RateLimiter()

    acquisition = await limiter.try_acquire_concurrent_slot_details(
        "org-1", max_concurrent=10, scope_key="ip:abc", scope_max_concurrent=1
    )
    assert acquisition is not None

    # Simulate the leak: never release. A second acquisition for the same
    # scope should be refused immediately (scope limit is 1)...
    blocked = await limiter.try_acquire_concurrent_slot_details(
        "org-1", max_concurrent=10, scope_key="ip:abc", scope_max_concurrent=1
    )
    assert blocked is None

    # ...but succeed once the short scope reaper window has passed, well
    # before the org's 2100s reaper would ever fire.
    time.sleep(1.2)
    recovered = await limiter.try_acquire_concurrent_slot_details(
        "org-1", max_concurrent=10, scope_key="ip:abc", scope_max_concurrent=1
    )
    assert recovered is not None
