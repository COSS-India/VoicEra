"""Member API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user
from app.database_init import ROLE_SUPER_ADMIN
from app.models.schemas import (
    AssignAdminRequest,
    MemberInvite,
    MemberJoin,
    RemoveMemberRequest,
    UserLoginResponse,
)
from app.services import member_service
from app.services import user_service

router = APIRouter(prefix="/members", tags=["members"])


def _require_active_org(current_user: dict[str, Any]) -> str:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organisation in token",
        )
    return org_id


@router.post(
    "/invite",
    response_model=dict[str, Any],
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    invite: MemberInvite,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Invite a user into the caller's active organisation (admin or super_admin)."""
    org_id = _require_active_org(current_user)
    result = member_service.invite_member(
        invite,
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


@router.post(
    "/join",
    response_model=UserLoginResponse,
    status_code=status.HTTP_201_CREATED,
)
async def join_organisation(body: MemberJoin) -> dict[str, Any]:
    """Public self-serve join via invite link (org_id as invite code)."""
    result = member_service.join_organisation(
        body.email,
        body.password,
        body.org_id,
    )
    if result["status"] == "fail":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"],
        )
    return user_service.auth_response_for_membership(
        result["email"],
        result["org_id"],
        result["role"],
        message=result["message"],
        is_first_login=result.get("is_first_login", False),
    )


@router.get("/{org_id}", response_model=dict[str, Any])
async def get_members(
    org_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """List members for an organisation (Bearer; must be a member of that org)."""
    membership = member_service.get_membership(current_user["email"], org_id)
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access members of this organization",
        )

    result = member_service.get_members_by_org(org_id)
    if result["status"] == "fail":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result["message"],
        )
    return result


@router.post("/assign-admin", response_model=dict[str, Any])
async def assign_admin(
    body: AssignAdminRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Promote a member to admin (super_admin only; active org from JWT)."""
    org_id = _require_active_org(current_user)
    if current_user.get("role") != ROLE_SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super admins can assign admins",
        )

    result = member_service.assign_admin(
        body,
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


@router.post("/remove", response_model=dict[str, Any])
async def remove_member(
    body: RemoveMemberRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Remove a member from the active organisation (super_admin only)."""
    org_id = _require_active_org(current_user)
    if current_user.get("role") != ROLE_SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super admins can remove members",
        )

    result = member_service.remove_member(
        body,
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
