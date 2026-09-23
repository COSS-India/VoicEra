"""Hard call-duration cap — Layer 3 of docs/developer/rate-limiting-plan.md.

An unconditional safety rail, not a rate limit: it has no IP or org context
(a telephony call has no meaningful client IP at all), no Redis dependency,
and applies regardless of any allowlist or exemption — see the plan's §8c.
The ceiling is always applied server-side so an org editing its own agent
config cannot escape it.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from loguru import logger

from apps.runtime.constants import (
    max_call_duration_ceiling_seconds,
    max_call_duration_seconds,
    rate_limit_enabled,
)

# Set on the finalize-call patch's `end_reason` when this guard ends the
# call, so it's visible in call logs rather than appearing as a mystery
# hangup. Requires CallLogUpdateRequest.end_reason (apps/api/app/models/schemas.py).
MAX_DURATION_END_REASON = "max_duration"


def effective_call_duration_seconds(behaviour: dict) -> int:
    """min(agent's own call_timeout_seconds, ceiling) — the ceiling always
    wins, so raising an agent's own timeout can never exceed it."""
    ceiling = max_call_duration_ceiling_seconds()
    agent_timeout = (behaviour or {}).get("call_timeout_seconds")
    if agent_timeout:
        try:
            return max(1, min(int(agent_timeout), ceiling))
        except (TypeError, ValueError):
            pass
    return max(1, min(max_call_duration_seconds(), ceiling))


def configured_call_duration_seconds(behaviour: dict) -> int | None:
    """The cap to actually arm for this call, or ``None`` to arm nothing.

    Gated on ``RATE_LIMIT_ENABLED`` like every other layer of the plan. Without
    this gate the guard is the one change that takes effect on merge: with no
    per-agent ``call_timeout_seconds`` set, every call would be cut at
    ``MAX_CALL_DURATION_SECONDS`` (600s) as soon as the code ships, rather than
    when an operator turns limiting on.
    """
    if not rate_limit_enabled():
        return None
    return effective_call_duration_seconds(behaviour)


class DurationGuard:
    """Fires ``on_timeout`` once after ``duration_seconds``, unless cancelled first."""

    def __init__(
        self,
        duration_seconds: float,
        on_timeout: Callable[[], Awaitable[None]],
    ) -> None:
        self._duration_seconds = duration_seconds
        self._on_timeout = on_timeout
        self._task: asyncio.Task | None = None
        self.fired = False

    def start(self) -> None:
        if self._duration_seconds <= 0:
            return
        self._task = asyncio.create_task(self._run(), name="duration_guard")

    async def _run(self) -> None:
        try:
            await asyncio.sleep(self._duration_seconds)
        except asyncio.CancelledError:
            return
        self.fired = True
        try:
            await self._on_timeout()
        except Exception:
            logger.exception("duration_guard on_timeout callback failed")

    def cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
