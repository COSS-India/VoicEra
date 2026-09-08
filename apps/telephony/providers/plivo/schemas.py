"""Pydantic schemas for Plivo telephony request/response shapes."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class PlivoApplicationCreate(BaseModel):
    """Schema for creating a Plivo application."""

    agent_type: str
    answer_url: str


class PlivoApplicationResponse(BaseModel):
    """Schema for Plivo application response."""

    status: str
    message: str
    app_id: Optional[str] = None


class PlivoNumberLink(BaseModel):
    """Schema for linking a phone number to a Plivo application."""

    phone_number: str
    application_id: str


class PlivoNumberUnlink(BaseModel):
    """Schema for unlinking a phone number from a Plivo application."""

    phone_number: str
