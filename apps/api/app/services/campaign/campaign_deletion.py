"""Hard-delete a campaign and purge associated contact-source artifacts (DPDP)."""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.campaign import campaign_repository as repo
from app.storage.minio_client import MinIOStorage

logger = logging.getLogger(__name__)


def _purge_source_object(source_id: str) -> bool:
    """Remove the MinIO CSV when no campaign still references ``source_id``."""
    if not source_id:
        return False
    if repo.count_campaigns_with_source_id(source_id) > 0:
        return False
    try:
        MinIOStorage().remove_object(
            source_id, bucket_name=settings.MINIO_BUCKET
        )
    except Exception as exc:
        # Campaign + queued runs are already gone; surface storage failure in logs
        # without blocking the API response (same posture as knowledge MinIO delete).
        logger.warning(
            "campaign_source_purge_failed campaign_source_id=%s error=%s",
            source_id,
            exc,
        )
        return False
    return True


def delete_campaign_for_org(
    *,
    org_id: str,
    campaign_id: str,
    actor: str | None = None,
) -> dict[str, Any]:
    """Delete campaign document, queued runs, and unreferenced contact CSV.

    Returns a PII-free summary suitable for audit logging. Does not log phone
    numbers, CSV contents, or context variables.
    """
    doc = repo.get_campaign_for_org(org_id, campaign_id)
    source_id = str(doc.get("source_id") or "").strip()
    source_type = str(doc.get("source_type") or "csv")

    queued_deleted = repo.delete_queued_runs_for_campaign(campaign_id)
    repo.delete_campaign(campaign_id)

    source_purged = False
    if source_type == "csv" and source_id:
        source_purged = _purge_source_object(source_id)

    summary = {
        "event": "campaign_deleted",
        "org_id": org_id,
        "campaign_id": campaign_id,
        "actor": actor or "",
        "source_type": source_type,
        "source_id": source_id,
        "queued_runs_deleted": queued_deleted,
        "source_object_purged": source_purged,
    }
    logger.info(
        "campaign_deleted org_id=%s campaign_id=%s actor=%s source_id=%s "
        "queued_runs_deleted=%s source_object_purged=%s",
        org_id,
        campaign_id,
        actor or "",
        source_id,
        queued_deleted,
        source_purged,
    )
    return summary
