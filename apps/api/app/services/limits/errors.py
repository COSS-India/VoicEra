"""Exceptions raised by the limits package."""

from __future__ import annotations


class LimitExceeded(Exception):
    """Raised when a fixed-window or usage limit rejects a request.

    Mapped to HTTP 429 with ``Retry-After`` by the handler registered in
    ``app.main``. The body carries only ``scope`` and ``retry_after`` —
    nothing about the account, so a limiter response can never become an
    enumeration oracle (see rate-limiting-plan.md §9, S9).
    """

    def __init__(self, *, scope: str, limit: int, retry_after: int) -> None:
        self.scope = scope
        self.limit = limit
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded for scope={scope} limit={limit} "
            f"retry_after={retry_after}s"
        )
