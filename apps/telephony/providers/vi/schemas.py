"""VI telephony pydantic helpers."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ViOutboundQueued(BaseModel):
    """Shape returned after a VI OBD single-call queue (Phase 2+)."""

    status: str = "success"
    message: Optional[str] = None
    campaign_Ref_ID: Optional[str] = None
    dni: Optional[str] = None
    msisdn: Optional[str] = None
    raw: Optional[dict[str, Any]] = Field(default=None, repr=False)
