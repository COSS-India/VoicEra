"""Rate-limited campaign call dispatch via existing outbound service."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.services import call_log_service
from app.services.call_concurrency import (
    CallConcurrencySlot,
    call_concurrency,
    rate_limiter,
)
from app.services.campaign import campaign_repository as repo
from app.services.campaign.errors import (
    ConcurrentSlotAcquisitionError,
    PhoneNumberPoolExhaustedError,
)
from app.services.outbound_call_service import OutboundCallError, initiate_outbound_call
from app.services import agent_service, phone_number_service

logger = logging.getLogger(__name__)

CONCURRENT_SLOT_TIMEOUT = 120.0


class CampaignCallDispatcher:
    async def _resolve_from_numbers(
        self, org_id: str, agent_id: str, campaign: dict[str, Any]
    ) -> list[str]:
        override = campaign.get("from_number")
        if override:
            return [str(override)]
        numbers: list[str] = []
        try:
            agent = agent_service.get_agent(org_id, agent_id)
            linked = agent.get("linked_phone_number")
            if linked:
                numbers.append(str(linked))
        except Exception:
            pass
        for doc in phone_number_service.list_by_org(org_id):
            if doc.get("agent_id") == agent_id:
                num = doc.get("phone_number")
                if num and num not in numbers:
                    numbers.append(str(num))
        return numbers

    def _pool_scope(self, agent_id: str) -> str:
        return f"agent:{agent_id}"

    async def apply_rate_limit(self, org_id: str, rate_limit: int) -> None:
        while not await rate_limiter.acquire_token(org_id, rate_limit):
            await asyncio.sleep(0.05)

    async def acquire_concurrent_slot(
        self, org_id: str, campaign: dict[str, Any]
    ) -> CallConcurrencySlot:
        metadata = campaign.get("orchestrator_metadata") or {}
        max_concurrency = metadata.get("max_concurrency")
        scope_key = f"campaign:{campaign['campaign_id']}"
        try:
            return await call_concurrency.acquire_org_slot(
                org_id,
                source="campaign",
                timeout=CONCURRENT_SLOT_TIMEOUT,
                scope_key=scope_key,
                scope_max_concurrent=int(max_concurrency) if max_concurrency else None,
            )
        except Exception as exc:
            raise ConcurrentSlotAcquisitionError(str(exc)) from exc

    def _uses_exclusive_from_number_pool(self, numbers: list[str]) -> bool:
        """Rotate across CLIs when multiple numbers exist; a single CLI is shared."""
        return len(numbers) > 1

    async def acquire_from_number(
        self, org_id: str, agent_id: str, campaign: dict[str, Any]
    ) -> tuple[str | None, bool]:
        """Return (from_number, pool_managed). Single CLIs are reused concurrently."""
        pool_scope = self._pool_scope(agent_id)
        numbers = await self._resolve_from_numbers(org_id, agent_id, campaign)
        if not numbers:
            return None, False
        if not self._uses_exclusive_from_number_pool(numbers):
            return numbers[0], False
        await rate_limiter.initialize_from_number_pool(org_id, numbers, pool_scope)
        acquired = await rate_limiter.acquire_from_number(org_id, pool_scope)
        return acquired, True

    async def process_batch(self, campaign_id: str, batch_size: int = 10) -> int:
        campaign = repo.get_campaign_by_id(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        if campaign.get("state") != "running":
            logger.info("Campaign %s not running: %s", campaign_id, campaign.get("state"))
            return 0

        queued_runs = repo.claim_queued_runs_for_processing(
            campaign_id,
            scheduled_before=datetime.now(timezone.utc),
            limit=batch_size,
        )
        if not queued_runs:
            return 0

        org_id = str(campaign["org_id"])
        agent_id = str(campaign["agent_id"])
        processed_count = 0
        processed_ids: set[str] = set()

        for queued_run in queued_runs:
            qid = str(queued_run["queued_run_id"])
            try:
                await self.apply_rate_limit(
                    org_id, int(campaign.get("rate_limit_per_second") or 1)
                )
                slot = await self.acquire_concurrent_slot(org_id, campaign)
                result = await self.dispatch_call(queued_run, campaign, slot)
                repo.update_queued_run(
                    qid,
                    state="processed",
                    call_id=result["call_id"],
                    processed_at=datetime.now(timezone.utc).isoformat(),
                )
                processed_count += 1
                processed_ids.add(qid)
                current_processed = int(campaign.get("processed_rows") or 0) + 1
                repo.update_campaign(campaign_id, processed_rows=current_processed)
                campaign = repo.get_campaign_by_id(campaign_id) or campaign
            except asyncio.CancelledError:
                await self._return_unprocessed_claims(queued_runs, processed_ids)
                raise
            except PhoneNumberPoolExhaustedError:
                await self._return_unprocessed_claims(queued_runs, processed_ids)
                raise
            except ConcurrentSlotAcquisitionError:
                await self._return_unprocessed_claims(queued_runs, processed_ids)
                raise
            except Exception as exc:
                logger.warning("Error processing queued run %s: %s", qid, exc)
                repo.update_queued_run(
                    qid,
                    state="failed",
                    processed_at=datetime.now(timezone.utc).isoformat(),
                )

        return processed_count

    async def _return_unprocessed_claims(
        self,
        queued_runs: list[dict[str, Any]],
        processed_ids: set[str],
    ) -> None:
        ids = [
            str(q["queued_run_id"])
            for q in queued_runs
            if str(q["queued_run_id"]) not in processed_ids
        ]
        if ids:
            repo.return_processing_queued_runs_without_call(ids)

    async def dispatch_call(
        self,
        queued_run: dict[str, Any],
        campaign: dict[str, Any],
        concurrency_slot: CallConcurrencySlot,
    ) -> dict[str, Any]:
        org_id = str(campaign["org_id"])
        agent_id = str(campaign["agent_id"])
        campaign_id = str(campaign["campaign_id"])
        queued_run_id = str(queued_run["queued_run_id"])
        context = dict(queued_run.get("context_variables") or {})
        phone_number = str(context.get("phone_number") or "").strip()
        if not phone_number:
            raise ValueError(f"No phone number in queued run {queued_run_id}")

        from_number, pool_managed = await self.acquire_from_number(
            org_id, agent_id, campaign
        )
        if from_number is None:
            raise PhoneNumberPoolExhaustedError(organization_id=org_id)

        variables = {k: v for k, v in context.items() if k != "phone_number"}
        variables.update(
            {
                "campaign_id": campaign_id,
                "source_uuid": queued_run.get("source_uuid"),
                "caller_number": from_number,
                "called_number": phone_number,
                "direction": "outbound",
            }
        )
        pool_scope = self._pool_scope(agent_id)
        slot_bound = False
        call_id: str | None = None
        try:
            result = await initiate_outbound_call(
                org_id,
                agent_id,
                phone_number,
                from_number=from_number,
                custom_variables=variables,
            )
            call_id = str(result["call_id"])
            call_log_service.update_call_log(
                call_id,
                {"campaign_id": campaign_id, "queued_run_id": queued_run_id},
            )
            await call_concurrency.bind_call_slot(concurrency_slot, call_id)
            slot_bound = True
            if pool_managed:
                await rate_limiter.store_call_from_number_mapping(
                    call_id, org_id, from_number, pool_scope
                )
            return result
        except Exception:
            if slot_bound and call_id:
                await call_concurrency.release_call_slot(call_id)
            else:
                await call_concurrency.release_slot(concurrency_slot)
            if from_number and pool_managed:
                await rate_limiter.release_from_number(
                    org_id, from_number, pool_scope
                )
            raise

    async def release_call_slot(self, call_id: str) -> None:
        await call_concurrency.release_call_slot(call_id)
        mapping = await rate_limiter.get_call_from_number_mapping(call_id)
        if mapping:
            org_id, from_number, pool_scope = mapping
            await rate_limiter.release_from_number(org_id, from_number, pool_scope)
            await rate_limiter.delete_call_from_number_mapping(call_id)


campaign_call_dispatcher = CampaignCallDispatcher()
