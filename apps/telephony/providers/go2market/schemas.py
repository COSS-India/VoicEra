"""Go To Market Pydantic schemas."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class Go2MarketOutboundQueued(BaseModel):
    """Result of a queued Go To Market OBD dial."""

    status: str = "success"
    message: str = ""
    provider_call_sid: Optional[str] = None
    phoneno: Optional[str] = None
    serviceno: Optional[str] = None
    wss_url: Optional[str] = None
    call_uuid: Optional[Any] = None
