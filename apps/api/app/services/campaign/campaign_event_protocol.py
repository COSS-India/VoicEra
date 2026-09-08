"""Campaign event protocol for orchestrator communication."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class CampaignEventType(str, Enum):
    BATCH_COMPLETED = "batch_completed"
    BATCH_FAILED = "batch_failed"
    SYNC_STARTED = "sync_started"
    SYNC_COMPLETED = "sync_completed"
    SYNC_FAILED = "sync_failed"
    CAMPAIGN_STARTED = "campaign_started"
    CAMPAIGN_PAUSED = "campaign_paused"
    CAMPAIGN_RESUMED = "campaign_resumed"
    CAMPAIGN_COMPLETED = "campaign_completed"
    CAMPAIGN_FAILED = "campaign_failed"
    RETRY_NEEDED = "retry_needed"
    RETRY_SCHEDULED = "retry_scheduled"
    RETRY_FAILED = "retry_failed"
    CIRCUIT_BREAKER_TRIPPED = "circuit_breaker_tripped"


class RetryReason(str, Enum):
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    VOICEMAIL = "voicemail"
    FAILED = "failed"
    ERROR = "error"


@dataclass
class BaseCampaignEvent:
    type: str
    campaign_id: str = ""
    timestamp: str | None = None

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> BaseCampaignEvent:
        return cls(**json.loads(data))


@dataclass
class BatchCompletedEvent(BaseCampaignEvent):
    type: str = CampaignEventType.BATCH_COMPLETED
    processed_count: int = 0
    failed_count: int = 0
    batch_size: int = 0
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.metadata is None:
            self.metadata = {}


@dataclass
class BatchFailedEvent(BaseCampaignEvent):
    type: str = CampaignEventType.BATCH_FAILED
    error: str = ""
    processed_count: int = 0
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.metadata is None:
            self.metadata = {}


@dataclass
class SyncCompletedEvent(BaseCampaignEvent):
    type: str = CampaignEventType.SYNC_COMPLETED
    total_rows: int = 0
    source_type: str = ""
    source_id: str = ""
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.metadata is None:
            self.metadata = {}


@dataclass
class RetryNeededEvent(BaseCampaignEvent):
    type: str = CampaignEventType.RETRY_NEEDED
    call_id: str = ""
    queued_run_id: str = ""
    reason: str = ""
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.metadata is None:
            self.metadata = {}


@dataclass
class CircuitBreakerTrippedEvent(BaseCampaignEvent):
    type: str = CampaignEventType.CIRCUIT_BREAKER_TRIPPED
    failure_rate: float = 0.0
    failure_count: int = 0
    success_count: int = 0
    threshold: float = 0.0
    window_seconds: int = 0


@dataclass
class CampaignCompletedEvent(BaseCampaignEvent):
    type: str = CampaignEventType.CAMPAIGN_COMPLETED
    total_rows: int = 0
    processed_rows: int = 0
    failed_rows: int = 0
    duration_seconds: float | None = None


def parse_campaign_event(data: str) -> Any:
    try:
        parsed = json.loads(data)
        event_type = parsed.get("type")
        event_class_map = {
            CampaignEventType.BATCH_COMPLETED: BatchCompletedEvent,
            CampaignEventType.BATCH_FAILED: BatchFailedEvent,
            CampaignEventType.SYNC_COMPLETED: SyncCompletedEvent,
            CampaignEventType.RETRY_NEEDED: RetryNeededEvent,
            CampaignEventType.CIRCUIT_BREAKER_TRIPPED: CircuitBreakerTrippedEvent,
            CampaignEventType.CAMPAIGN_COMPLETED: CampaignCompletedEvent,
        }
        event_class = event_class_map.get(event_type)
        if event_class:
            return event_class(**parsed)
        return None
    except Exception:
        return None
