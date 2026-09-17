"""Backward-compatible re-exports for VI OBD."""

from apps.telephony.providers.vi.obd.client import ViObdClient
from apps.telephony.providers.vi.obd.errors import ViObdError
from apps.telephony.providers.vi.obd.normalize import normalize_msisdn
from apps.telephony.providers.vi.routing import resolve_vi_agent_id

__all__ = ["ViObdClient", "ViObdError", "normalize_msisdn", "resolve_vi_agent_id"]
