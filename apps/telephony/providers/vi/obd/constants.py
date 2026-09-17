"""VI OBD API constants."""

from __future__ import annotations

from zoneinfo import ZoneInfo

CPAAS_HOST = "https://cts.myvi.in:8443"
CPAAS_API_ROOT = f"{CPAAS_HOST}/Cpaas/api/v1"
DEFAULT_OBD_BASE = f"{CPAAS_API_ROOT}/obdcampaignapi"

TOKEN_TTL_SECS = 86400
TOKEN_REFRESH_MARGIN_SECS = 3600
REQUEST_TIMEOUT_SECS = 30
BULK_INGEST_CHUNK_SIZE = 500
DEFAULT_DIAL_TIMEOUT_SECS = 30

IST = ZoneInfo("Asia/Kolkata")
