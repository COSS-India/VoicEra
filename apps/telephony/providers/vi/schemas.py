"""Pydantic shapes for VI OBD responses (lightweight)."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ViOutboundQueued(BaseModel):
    status: str = "queued"
    provider: str = "vi"
    agent_id: str
    msisdn: str
    dni: str
    campaign_Ref_ID: Optional[Any] = None
    campainKey: Optional[str] = None
    message: str = Field(default="")
