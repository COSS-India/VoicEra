"""Tests for app.services.call_admission (Layer 2).

Unit-level tests run against the real Redis 7 instance (db 15, same as
test_limits.py) since the behaviour under test is the shared concurrency Lua.
A handful of router-level tests at the bottom exercise the actual HTTP path
(429 + rollback) using the same TestClient harness as test_outbound_calls.py.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.config import settings
from app.routers import calls
from app.services import call_admission
from app.services.call_admission import (
    CallAdmissionError,
    admit_call,
    bind_admitted_call,
    release_admitted_call,
)
from app.services.call_concurrency import service as call_concurrency_module
from app.services.call_concurrency.rate_limiter import RateLimiter
from app.services.limits import policy
from app.services.limits.counters import counters as limits_counters
from app.utils import client_ip

TEST_REDIS_URL = os.environ.get(
    "RTK_TEST_REDIS_URL", "redis://:redissecret@localhost:6379/15"
)


def _make_request(client_host: str = "203.0.113.5") -> Request:
    scope = {"type": "http", "client": (client_host, 12345), "headers": []}
    return Request(scope)


@pytest_asyncio.fixture(autouse=True)
async def _clean_redis():
    client = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
    await client.flushdb()
    yield
    await client.flushdb()
    await client.aclose()


@pytest.fixture(autouse=True)
def _admission_settings(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", TEST_REDIS_URL)
    monkeypatch.setattr(settings, "RATE_LIMIT_IP_SALT", "test-salt")
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", True)
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
    monkeypatch.setattr(settings, "RATE_LIMIT_IP_ALLOWLIST", "")
    monkeypatch.setattr(settings, "MAX_CONCURRENT_CALLS_PER_IP", 2)
    monkeypatch.setattr(settings, "DEFAULT_ORG_CONCURRENCY_LIMIT", 10)
    monkeypatch.setattr(settings, "ORG_DAILY_CALL_SECONDS", 14400)
    # Fresh RateLimiter so stale_call_timeout is derived from patched settings,
    # and reset the shared call_concurrency service to use it.
    fresh_limiter = RateLimiter()
    monkeypatch.setattr(call_concurrency_module, "rate_limiter", fresh_limiter)
    # pytest-asyncio gives each test its own event loop, but both `counters`
    # (limits/counters.py) and the RateLimiter it wraps are process-global
    # singletons in production (correct there — uvicorn runs one loop for
    # the process lifetime). Reset the cached client/script-sha state so
    # each test binds a fresh connection to *its* loop instead of reusing
    # one opened in a previous test's already-closed loop.
    monkeypatch.setattr(limits_counters, "_client", None)
    monkeypatch.setattr(limits_counters, "_incr_sha", None)
    monkeypatch.setattr(limits_counters, "_claim_sha", None)
    policy.invalidate_org_cache()
    client_ip._parsed_allowlist.cache_clear()
    yield
    policy.invalidate_org_cache()


@pytest.fixture(autouse=True)
def _org_lookup(monkeypatch):
    """No Organizations doc for these org ids — falls back to env defaults."""
    monkeypatch.setattr(policy, "_cached_org_lookup", lambda org_id: None)


# ---------------------------------------------------------------------------
# admit_call — disabled is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_admits_unconditionally(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    admitted = await admit_call(org_id="org-x", call_kind="outbound")
    assert admitted.slot is None


# ---------------------------------------------------------------------------
# Org concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_concurrency_admits_up_to_limit_then_denies(monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_ORG_CONCURRENCY_LIMIT", 2)
    a = await admit_call(org_id="org-conc", call_kind="outbound")
    b = await admit_call(org_id="org-conc", call_kind="outbound")
    assert a.slot is not None and b.slot is not None
    with pytest.raises(CallAdmissionError) as exc_info:
        await admit_call(org_id="org-conc", call_kind="outbound")
    assert exc_info.value.reason == "concurrency_org"


@pytest.mark.asyncio
async def test_release_admitted_call_frees_the_slot(monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_ORG_CONCURRENCY_LIMIT", 1)
    admitted = await admit_call(org_id="org-release", call_kind="outbound")
    assert admitted.slot is not None
    await release_admitted_call(admitted)
    # Freed — a second admission for the same org now succeeds.
    again = await admit_call(org_id="org-release", call_kind="outbound")
    assert again.slot is not None


@pytest.mark.asyncio
async def test_bind_admitted_call_survives_without_admission(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    admitted = await admit_call(org_id="org-x", call_kind="outbound")
    # Must not raise even though there's no real slot to bind.
    await bind_admitted_call(admitted, "call-123")
    await release_admitted_call(admitted)


# ---------------------------------------------------------------------------
# Per-IP concurrency (web calls only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_ip_concurrency_applies_only_to_web_calls():
    req = _make_request("203.0.113.10")
    # Two web calls from the same IP admitted (limit 2), a third denied.
    a = await admit_call(org_id="org-1", call_kind="web", request=req)
    b = await admit_call(org_id="org-1", call_kind="web", request=req)
    assert a.slot and b.slot
    with pytest.raises(CallAdmissionError) as exc_info:
        await admit_call(org_id="org-1", call_kind="web", request=req)
    assert exc_info.value.reason == "concurrency_ip"


@pytest.mark.asyncio
async def test_per_ip_concurrency_skipped_for_inbound_and_outbound():
    req = _make_request("203.0.113.10")
    # Same IP, but call_kind != "web": no per-IP scope applied, so many
    # "calls" from one IP don't trip anything (org concurrency is generous
    # in this test via the default fixture setting).
    for _ in range(5):
        admitted = await admit_call(
            org_id="org-1", call_kind="outbound", request=req
        )
        assert admitted.slot is not None


@pytest.mark.asyncio
async def test_different_ips_do_not_share_the_per_ip_counter():
    req_a = _make_request("203.0.113.10")
    req_b = _make_request("198.51.100.20")
    await admit_call(org_id="org-1", call_kind="web", request=req_a)
    await admit_call(org_id="org-1", call_kind="web", request=req_a)
    # req_a is now at its limit of 2; req_b is a fresh counter.
    admitted = await admit_call(org_id="org-1", call_kind="web", request=req_b)
    assert admitted.slot is not None


# ---------------------------------------------------------------------------
# Exemptions — must skip per-IP only, never org-scoped checks (S8a/S8b)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allowlisted_ip_skips_per_ip_but_not_org_concurrency(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_IP_ALLOWLIST", "203.0.113.10")
    monkeypatch.setattr(settings, "DEFAULT_ORG_CONCURRENCY_LIMIT", 1)
    client_ip._parsed_allowlist.cache_clear()
    req = _make_request("203.0.113.10")

    # Per-IP limit of 2 would normally deny a 3rd web call from this IP; the
    # allowlist means it never even gets checked. But the org limit (1) is
    # unrelated and must still apply.
    admitted = await admit_call(org_id="org-allow", call_kind="web", request=req)
    assert admitted.slot is not None
    with pytest.raises(CallAdmissionError) as exc_info:
        await admit_call(org_id="org-allow", call_kind="web", request=req)
    assert exc_info.value.reason == "concurrency_org"


@pytest.mark.asyncio
async def test_internal_service_subject_skips_per_ip_but_not_org_concurrency(
    monkeypatch,
):
    """Regression test for the failure mode found in review: the bot
    identity must never be exempt from an org-scoped limit — see
    docs/developer/rate-limiting-plan.md §8b."""
    monkeypatch.setattr(settings, "DEFAULT_ORG_CONCURRENCY_LIMIT", 1)
    req = _make_request("203.0.113.10")

    admitted = await admit_call(
        org_id="org-bot",
        call_kind="web",
        request=req,
        current_user_email="bot@voicera.internal",
    )
    assert admitted.slot is not None
    with pytest.raises(CallAdmissionError) as exc_info:
        await admit_call(
            org_id="org-bot",
            call_kind="web",
            request=req,
            current_user_email="bot@voicera.internal",
        )
    assert exc_info.value.reason == "concurrency_org"


# ---------------------------------------------------------------------------
# Org daily quota
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_quota_zero_means_unconfigured_not_zero_budget(monkeypatch):
    monkeypatch.setattr(settings, "ORG_DAILY_CALL_SECONDS", 0)
    admitted = await admit_call(org_id="org-noquota", call_kind="outbound")
    assert admitted.slot is not None


@pytest.mark.asyncio
async def test_daily_quota_rejects_when_exhausted(monkeypatch):
    from app.services.limits.counters import counters, utc_day_key

    monkeypatch.setattr(settings, "ORG_DAILY_CALL_SECONDS", 100)
    await counters.add_usage(f"usage:dur:org-quota:{utc_day_key()}", 95, ttl=60)
    with pytest.raises(CallAdmissionError) as exc_info:
        await admit_call(org_id="org-quota", call_kind="outbound")
    assert exc_info.value.reason == "quota"


@pytest.mark.asyncio
async def test_daily_quota_rejects_with_less_than_30s_remaining(monkeypatch):
    from app.services.limits.counters import counters, utc_day_key

    monkeypatch.setattr(settings, "ORG_DAILY_CALL_SECONDS", 100)
    await counters.add_usage(f"usage:dur:org-quota2:{utc_day_key()}", 75, ttl=60)
    # 25s remaining < 30s floor — still a rejection, not just an exact-zero check.
    with pytest.raises(CallAdmissionError):
        await admit_call(org_id="org-quota2", call_kind="outbound")


# ---------------------------------------------------------------------------
# Router-level: 429 + rollback
# ---------------------------------------------------------------------------


def _admin_user() -> dict[str, Any]:
    return {"email": "admin@example.com", "org_id": "org-1", "role": "admin"}


class _FakeCollection:
    def __init__(self, store: dict[Any, dict[str, Any]], key_fn) -> None:
        self._store = store
        self._key_fn = key_fn

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self._store.values():
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    def insert_one(self, doc: dict[str, Any]) -> None:
        self._store[self._key_fn(doc)] = dict(doc)


def test_router_returns_429_and_never_creates_calllog_when_org_saturated(
    monkeypatch,
):
    """Router-level integration test.

    TestClient drives the FastAPI app through its own event loop, distinct
    from any loop this (sync) test function might otherwise share — so the
    org's concurrency slot is saturated with a plain synchronous Redis client
    directly (mirroring what ``try_acquire_concurrent_slot_details`` reads),
    rather than by awaiting ``admit_call`` here, to avoid binding the shared
    ``RateLimiter``'s aioredis connection to two different event loops.
    """
    import redis as sync_redis

    monkeypatch.setattr(settings, "DEFAULT_ORG_CONCURRENCY_LIMIT", 1)
    call_store: dict[str, dict[str, Any]] = {}
    agent_store: dict[tuple[str, str], dict[str, Any]] = {
        ("org-1", "agent-1"): {
            "agent_id": "agent-1",
            "org_id": "org-1",
            "name": "WS Agent",
            "status": "active",
            "agent_category": "websocket",
        },
    }

    def _fake_db() -> dict[str, Any]:
        return {
            "CallLogs": _FakeCollection(call_store, lambda d: d["call_id"]),
            "Agents": _FakeCollection(agent_store, lambda d: (d["org_id"], d["agent_id"])),
        }

    app = FastAPI()
    app.include_router(calls.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _admin_user
    client = TestClient(app)

    # Occupy org-1's one concurrency slot, as if another call already holds
    # it. Score must be "now", not 0 — the reaper treats anything older than
    # stale_call_timeout as dead and would otherwise remove this before the
    # concurrency check even runs.
    import time as _time

    sync_client = sync_redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    sync_client.zadd("concurrent_calls:org-1", {"pre-existing-slot": _time.time()})

    with patch(
        "app.services.call_log_service.get_database", side_effect=_fake_db
    ), patch("app.services.agent_service.get_database", side_effect=_fake_db):
        response = client.post(
            "/api/v1/calls/web", json={"agent_id": "agent-1"}
        )

    assert response.status_code == 429
    assert response.headers.get("Retry-After")
    assert call_store == {}  # register_web_call was never reached
