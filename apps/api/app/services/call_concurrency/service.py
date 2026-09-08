"""Org-wide and campaign-scoped concurrent call slots."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from app.config import settings
from app.services.call_concurrency.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallConcurrencySlot:
    organization_id: str
    slot_id: str
    max_concurrent: int
    source: str
    scope_key: str | None = None


class CallConcurrencyLimitError(Exception):
    def __init__(
        self,
        *,
        organization_id: str,
        source: str,
        wait_time: float,
        max_concurrent: int,
    ) -> None:
        self.organization_id = organization_id
        self.source = source
        self.wait_time = wait_time
        self.max_concurrent = max_concurrent
        super().__init__(
            f"Concurrent call limit reached for org {organization_id} "
            f"(source={source}, limit={max_concurrent}, waited={wait_time:.1f}s)"
        )


class CallSlotAlreadyBoundError(Exception):
    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        super().__init__(f"Call {call_id} already has an active call slot")


class CallConcurrencyService:
    def __init__(self) -> None:
        self.default_concurrent_limit = int(settings.DEFAULT_ORG_CONCURRENCY_LIMIT)

    async def get_org_concurrent_limit(self, organization_id: str) -> int:
        from app.services.campaign.campaign_repository import get_org_concurrent_limit

        return get_org_concurrent_limit(organization_id)

    async def acquire_org_slot(
        self,
        organization_id: str,
        *,
        source: str,
        timeout: float = 0,
        scope_key: str | None = None,
        scope_max_concurrent: int | None = None,
        retry_interval: float = 1,
    ) -> CallConcurrencySlot:
        max_concurrent = await self.get_org_concurrent_limit(organization_id)
        if scope_max_concurrent is not None:
            scope_max_concurrent = int(scope_max_concurrent)
        wait_start = time.time()
        while True:
            acquisition = await rate_limiter.try_acquire_concurrent_slot_details(
                organization_id,
                max_concurrent,
                scope_key=scope_key,
                scope_max_concurrent=scope_max_concurrent,
            )
            if acquisition:
                return CallConcurrencySlot(
                    organization_id=organization_id,
                    slot_id=acquisition.slot_id,
                    max_concurrent=max_concurrent,
                    source=source,
                    scope_key=scope_key,
                )
            wait_time = time.time() - wait_start
            if wait_time >= timeout:
                raise CallConcurrencyLimitError(
                    organization_id=organization_id,
                    source=source,
                    wait_time=wait_time,
                    max_concurrent=max_concurrent,
                )
            await asyncio.sleep(min(retry_interval, max(0, timeout - wait_time)))

    async def bind_call_slot(self, slot: CallConcurrencySlot, call_id: str) -> None:
        stored = await rate_limiter.store_call_slot_mapping_if_absent(
            call_id,
            slot.organization_id,
            slot.slot_id,
            scope_key=slot.scope_key,
        )
        if stored:
            return
        await self.release_slot(slot)
        raise CallSlotAlreadyBoundError(call_id)

    async def release_slot(self, slot: CallConcurrencySlot | None) -> bool:
        if slot is None:
            return False
        released = await rate_limiter.release_concurrent_slot(
            slot.organization_id, slot.slot_id, scope_key=slot.scope_key
        )
        return bool(released)

    async def release_call_slot(self, call_id: str) -> bool:
        mapping = await rate_limiter.get_call_slot_mapping(call_id)
        if not mapping:
            return False
        org_id, slot_id, scope_key = mapping
        released = await rate_limiter.release_concurrent_slot(
            org_id, slot_id, scope_key=scope_key
        )
        if released is None:
            return False
        await rate_limiter.delete_call_slot_mapping(call_id)
        return bool(released)


call_concurrency = CallConcurrencyService()
