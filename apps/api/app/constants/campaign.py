"""Default configuration for outbound campaigns."""

from __future__ import annotations

import os

DEFAULT_ORG_CONCURRENCY_LIMIT = max(
    1, int(os.getenv("DEFAULT_ORG_CONCURRENCY_LIMIT", "10"))
)

DEFAULT_CAMPAIGN_RETRY_CONFIG = {
    "enabled": True,
    "max_retries": 2,
    "retry_delay_seconds": 120,
    "retry_on_busy": True,
    "retry_on_no_answer": True,
    "retry_on_voicemail": False,
}

DEFAULT_CIRCUIT_BREAKER_CONFIG = {
    "enabled": True,
    "failure_threshold": 0.5,
    "window_seconds": 300,
    "min_calls_in_window": 5,
}

CAMPAIGN_EVENTS_CHANNEL = "campaign_events"
