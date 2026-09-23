"""Tests for the Layer 3 hard call-duration cap.

See docs/developer/rate-limiting-plan.md. Covers:
- effective_call_duration_seconds: agent override vs ceiling clamp.
- DurationGuard: fires at the limit, cancels cleanly on normal hangup.
- run_with_lifecycle: end_reason is set on the finalize patch when the guard
  fires, and left unset on a normal end.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from apps.runtime.services.pipecat import duration_guard as duration_guard_module
from apps.runtime.services.pipecat import lifecycle as lifecycle_module
from apps.runtime.services.pipecat.duration_guard import (
    MAX_DURATION_END_REASON,
    DurationGuard,
    configured_call_duration_seconds,
    effective_call_duration_seconds,
)
from apps.runtime.services.pipecat.lifecycle import SessionContext, run_with_lifecycle


# ---------------------------------------------------------------------------
# effective_call_duration_seconds
# ---------------------------------------------------------------------------


def test_agent_timeout_under_ceiling_wins(monkeypatch):
    monkeypatch.setattr(duration_guard_module, "max_call_duration_ceiling_seconds", lambda: 1800)
    monkeypatch.setattr(duration_guard_module, "max_call_duration_seconds", lambda: 600)
    assert effective_call_duration_seconds({"call_timeout_seconds": 300}) == 300


def test_agent_timeout_over_ceiling_is_clamped(monkeypatch):
    """The ceiling is an unconditional safety rail — an org cannot raise its
    own agent's call_timeout_seconds past it (rate-limiting-plan.md §8c)."""
    monkeypatch.setattr(duration_guard_module, "max_call_duration_ceiling_seconds", lambda: 1800)
    monkeypatch.setattr(duration_guard_module, "max_call_duration_seconds", lambda: 600)
    assert effective_call_duration_seconds({"call_timeout_seconds": 3600}) == 1800


def test_missing_agent_timeout_uses_env_default(monkeypatch):
    monkeypatch.setattr(duration_guard_module, "max_call_duration_ceiling_seconds", lambda: 1800)
    monkeypatch.setattr(duration_guard_module, "max_call_duration_seconds", lambda: 600)
    assert effective_call_duration_seconds({}) == 600
    assert effective_call_duration_seconds(None) == 600


def test_env_default_over_ceiling_is_also_clamped(monkeypatch):
    monkeypatch.setattr(duration_guard_module, "max_call_duration_ceiling_seconds", lambda: 60)
    monkeypatch.setattr(duration_guard_module, "max_call_duration_seconds", lambda: 600)
    assert effective_call_duration_seconds({}) == 60


def test_invalid_agent_timeout_falls_back_to_env_default(monkeypatch):
    monkeypatch.setattr(duration_guard_module, "max_call_duration_ceiling_seconds", lambda: 1800)
    monkeypatch.setattr(duration_guard_module, "max_call_duration_seconds", lambda: 600)
    assert effective_call_duration_seconds({"call_timeout_seconds": "not-a-number"}) == 600


# ---------------------------------------------------------------------------
# configured_call_duration_seconds — the RATE_LIMIT_ENABLED gate
# ---------------------------------------------------------------------------


def test_guard_is_not_armed_while_rate_limiting_is_disabled(monkeypatch):
    """Default-off, like every other layer of the plan: shipping this code
    must not start cutting calls at MAX_CALL_DURATION_SECONDS until an
    operator sets RATE_LIMIT_ENABLED=true."""
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    assert configured_call_duration_seconds({}) is None
    assert configured_call_duration_seconds({"call_timeout_seconds": 300}) is None


def test_guard_is_armed_when_rate_limiting_is_enabled(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setattr(duration_guard_module, "max_call_duration_ceiling_seconds", lambda: 1800)
    monkeypatch.setattr(duration_guard_module, "max_call_duration_seconds", lambda: 600)
    assert configured_call_duration_seconds({}) == 600
    assert configured_call_duration_seconds({"call_timeout_seconds": 300}) == 300


# ---------------------------------------------------------------------------
# DurationGuard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_fires_at_the_limit():
    fired = asyncio.Event()

    async def _on_timeout() -> None:
        fired.set()

    guard = DurationGuard(0.05, _on_timeout)
    guard.start()
    await asyncio.wait_for(fired.wait(), timeout=1)
    assert guard.fired


@pytest.mark.asyncio
async def test_guard_cancelled_before_firing_never_calls_on_timeout():
    on_timeout = AsyncMock()
    guard = DurationGuard(1.0, on_timeout)
    guard.start()
    await asyncio.sleep(0.02)
    guard.cancel()
    await asyncio.sleep(0.05)
    on_timeout.assert_not_awaited()
    assert not guard.fired


def test_guard_with_zero_duration_never_starts_a_task():
    guard = DurationGuard(0, AsyncMock())
    guard.start()
    assert guard._task is None


# ---------------------------------------------------------------------------
# run_with_lifecycle integration
# ---------------------------------------------------------------------------


class _FakeWorker:
    pass


class _FakeRunner:
    """Minimal stand-in for pipecat's WorkerRunner: `run()` blocks until
    `end()`/`cancel()` sets the shutdown event, exactly like the real one."""

    def __init__(self, handle_sigint: bool = False) -> None:
        self.ended_reason: str | None = None
        self._shutdown = asyncio.Event()

    async def add_workers(self, *workers: Any) -> None:
        pass

    async def run(self) -> None:
        await self._shutdown.wait()

    async def end(self, reason: str | None = None) -> None:
        self.ended_reason = reason
        self._shutdown.set()


@pytest.fixture(autouse=True)
def _fake_runner(monkeypatch):
    monkeypatch.setattr(lifecycle_module, "WorkerRunner", _FakeRunner)


@pytest.fixture
def _mock_backend(monkeypatch):
    update_call = AsyncMock()
    notify = AsyncMock()
    monkeypatch.setattr(lifecycle_module.backend_client, "update_call", update_call)
    monkeypatch.setattr(
        lifecycle_module.backend_client, "notify_campaign_call_status", notify
    )
    return update_call


@pytest.mark.asyncio
async def test_lifecycle_sets_end_reason_when_guard_fires(_mock_backend):
    ctx = SessionContext(
        org_id="org-1",
        call_id="call-1",
        session_label="test",
        finalize_call=True,
        agent_id="agent-1",
        sample_rate=8000,
        max_duration_seconds=0.05,
    )
    await run_with_lifecycle(_FakeWorker(), ctx)

    _mock_backend.assert_awaited_once()
    patch = _mock_backend.await_args.args[2]
    assert patch["end_reason"] == MAX_DURATION_END_REASON


@pytest.mark.asyncio
async def test_lifecycle_leaves_end_reason_unset_on_normal_hangup(_mock_backend, monkeypatch):
    ctx = SessionContext(
        org_id="org-1",
        call_id="call-1",
        session_label="test",
        finalize_call=True,
        agent_id="agent-1",
        sample_rate=8000,
        max_duration_seconds=10.0,  # long enough it will never fire in this test
    )

    # Simulate a normal hangup racing the (long) guard: end the runner
    # directly, well before the guard's duration elapses.
    original_run_with_lifecycle = run_with_lifecycle

    async def _hangup_after_delay(runner: _FakeRunner) -> None:
        await asyncio.sleep(0.02)
        await runner.end(reason=None)

    # Patch WorkerRunner to auto-hangup shortly after construction.
    class _AutoHangupRunner(_FakeRunner):
        def __init__(self, handle_sigint: bool = False) -> None:
            super().__init__(handle_sigint)
            asyncio.get_event_loop().create_task(_hangup_after_delay(self))

    monkeypatch.setattr(lifecycle_module, "WorkerRunner", _AutoHangupRunner)

    await run_with_lifecycle(_FakeWorker(), ctx)

    _mock_backend.assert_awaited_once()
    patch = _mock_backend.await_args.args[2]
    assert "end_reason" not in patch


@pytest.mark.asyncio
async def test_lifecycle_guard_is_cancelled_on_normal_hangup_no_dangling_task(
    _mock_backend, monkeypatch
):
    """The guard's asyncio task must not still be pending after
    run_with_lifecycle returns on a normal hangup — otherwise it leaks and
    could fire late against a call that already finalised."""
    ctx = SessionContext(
        org_id="org-1",
        call_id="call-1",
        session_label="test",
        finalize_call=True,
        agent_id="agent-1",
        sample_rate=8000,
        max_duration_seconds=10.0,
    )

    captured_guard: dict[str, DurationGuard] = {}
    original_init = DurationGuard.__init__

    def _capturing_init(self, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        captured_guard["guard"] = self

    monkeypatch.setattr(DurationGuard, "__init__", _capturing_init)

    class _AutoHangupRunner(_FakeRunner):
        def __init__(self, handle_sigint: bool = False) -> None:
            super().__init__(handle_sigint)

            async def _hangup() -> None:
                await asyncio.sleep(0.02)
                await self.end(reason=None)

            asyncio.get_event_loop().create_task(_hangup())

    monkeypatch.setattr(lifecycle_module, "WorkerRunner", _AutoHangupRunner)

    await run_with_lifecycle(_FakeWorker(), ctx)
    # guard.cancel() only schedules the cancellation; give the event loop a
    # turn to actually deliver it before asserting.
    await asyncio.sleep(0)

    guard = captured_guard["guard"]
    assert guard._task is not None
    assert guard._task.cancelled() or guard._task.done()
    assert not guard.fired
