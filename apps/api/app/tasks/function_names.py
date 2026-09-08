"""ARQ function name constants."""

from __future__ import annotations

from enum import Enum


class FunctionNames(str, Enum):
    SYNC_CAMPAIGN_SOURCE = "sync_campaign_source"
    PROCESS_CAMPAIGN_BATCH = "process_campaign_batch"
