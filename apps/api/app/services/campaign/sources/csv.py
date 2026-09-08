"""Campaign CSV source sync."""

from __future__ import annotations

import csv
import hashlib
import logging
from io import StringIO

from app.services.campaign import campaign_repository as repo
from app.services.campaign.source_sync import (
    CampaignSourceSyncService,
    ValidationError,
    ValidationResult,
)
from app.storage.minio_client import MinIOStorage

logger = logging.getLogger(__name__)


class CSVSyncService(CampaignSourceSyncService):
    async def _fetch_csv_data(self, file_key: str) -> list[list[str]]:
        storage = MinIOStorage()
        content = await storage.get_object_bytes(file_key)
        text = content.decode("utf-8-sig")
        reader = csv.reader(StringIO(text))
        return list(reader)

    async def validate_source(
        self, source_id: str, organization_id: str | None = None
    ) -> ValidationResult:
        try:
            csv_data = await self._fetch_csv_data(source_id)
        except Exception as exc:
            return ValidationResult(
                is_valid=False,
                error=ValidationError(message=str(exc)),
            )
        if not csv_data or len(csv_data) < 2:
            return ValidationResult(
                is_valid=False,
                error=ValidationError(
                    message="CSV file must have a header row and at least one data row"
                ),
            )
        return self.validate_source_data(csv_data[0], csv_data[1:])

    async def sync_source_data(self, campaign_id: str) -> int:
        campaign = repo.get_campaign_by_id(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        file_key = str(campaign.get("source_id") or "")
        csv_data = await self._fetch_csv_data(file_key)
        if not csv_data or len(csv_data) < 2:
            logger.warning("No data in CSV for campaign %s", campaign_id)
            return 0
        headers = self.normalize_headers(csv_data[0])
        rows = csv_data[1:]
        file_hash = hashlib.md5(file_key.encode()).hexdigest()[:8]
        queued_runs = []
        for idx, row_values in enumerate(rows, 1):
            context_vars = self.build_context_variables(headers, row_values)
            if not context_vars.get("phone_number"):
                continue
            queued_runs.append(
                {
                    "campaign_id": campaign_id,
                    "source_uuid": f"csv_{file_hash}_row_{idx}",
                    "context_variables": context_vars,
                    "state": "queued",
                }
            )
        if queued_runs:
            repo.bulk_create_queued_runs(queued_runs)
        repo.update_campaign(
            campaign_id,
            total_rows=len(queued_runs),
            source_sync_status="completed",
        )
        return len(queued_runs)
