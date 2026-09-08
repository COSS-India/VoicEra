"""Pydantic schemas for Vobiz telephony request/response shapes."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class VobizApplicationCreate(BaseModel):
    """Schema for creating a Vobiz application."""

    agent_type: str
    answer_url: str


class VobizApplicationResponse(BaseModel):
    """Schema for Vobiz application response."""

    status: str
    message: str
    app_id: Optional[str] = None


class VobizNumberLink(BaseModel):
    """Schema for linking a phone number to a Vobiz application."""

    phone_number: str
    application_id: str


class VobizNumberUnlink(BaseModel):
    """Schema for unlinking a phone number from a Vobiz application."""

    phone_number: str
