"""VI Pydantic schemas."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ViOutboundQueued(BaseModel):
    """Result of a queued VI OBD dial."""

    status: str = "success"
    message: str = ""
    campaign_Ref_ID: Optional[Any] = None
    campainKey: Optional[str] = None
    dni: Optional[str] = None
    flow_id: Optional[str] = None
    msisdn: Optional[str] = None
    call_uuid: Optional[Any] = None
