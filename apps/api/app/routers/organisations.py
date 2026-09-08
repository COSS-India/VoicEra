"""Organisation API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user
from app.database_init import ROLE_SUPER_ADMIN
from app.services import user_service

router = APIRouter(prefix="/organisations", tags=["organisations"])


@router.delete("/{org_id}", response_model=dict[str, Any])
async def delete_organisation(
    org_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Delete an organisation (super_admin only).

    Removes all memberships for that org. User accounts are kept so members
    retain access to any other organisations they belong to.
    """
    if current_user.get("role") != ROLE_SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super admins can delete an organisation",
        )
    if current_user.get("org_id") != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Switch to this organisation before deleting it",
        )

    result = user_service.delete_active_organisation(
        current_user["email"],
        org_id,
        current_user.get("role") or "",
    )
    if result["status"] == "fail":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"],
        )
    return result
