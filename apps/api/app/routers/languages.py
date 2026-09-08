"""Language catalog routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from apps.providers.languages import canonical_languages

router = APIRouter(tags=["languages"])


@router.get("/languages")
async def get_languages(
    _current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, dict[str, str]]:
    """Canonical language id → label map for the agent-builder picker."""
    return {"languages": canonical_languages()}
