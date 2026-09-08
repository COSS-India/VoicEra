"""User API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import create_access_token, get_current_user, verify_api_key
from app.database_init import ROLE_ADMIN
from app.models.schemas import (
    BotTokenRequest,
    BotTokenResponse,
    CheckEmailResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    SwitchOrganisationRequest,
    UserCreate,
    UserLogin,
    UserLoginResponse,
    UserResponse,
)
from app.services import org_service, user_service

router = APIRouter(prefix="/users", tags=["users"])

# Synthetic subject for service JWTs minted via INTERNAL_API_KEY.
BOT_SERVICE_EMAIL = "bot@voicera.internal"


@router.post("/signup", response_model=UserLoginResponse, status_code=status.HTTP_201_CREATED)
async def sign_up(user_data: UserCreate) -> dict[str, Any]:
    """Create a user and organisation; caller becomes super_admin and receives a JWT."""
    result = user_service.sign_up_user(user_data)
    if result["status"] == "fail":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"],
        )
    return result


@router.post("/login", response_model=UserLoginResponse)
async def login(credentials: UserLogin) -> dict[str, Any]:
    """Authenticate and return a JWT for the user's default organisation."""
    result = user_service.validate_user_and_get_token(
        credentials.email,
        credentials.password,
    )
    if result["status"] == "fail":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result["message"],
        )
    return result


@router.post("/bot/token", response_model=BotTokenResponse)
async def bot_token(
    body: BotTokenRequest,
    _: bool = Depends(verify_api_key),
) -> dict[str, Any]:
    """Mint an org-scoped JWT for service-to-service callers (Pipecat / voice).

    Authenticated with ``X-API-Key: INTERNAL_API_KEY``. Pass ``org_id`` from
    call/agent context. Use ``access_token`` as ``Authorization: Bearer`` for
    subsequent API calls.
    """
    org = org_service.get_organisation(body.org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organisation not found: {body.org_id}",
        )

    access_token = create_access_token(
        data={
            "sub": BOT_SERVICE_EMAIL,
            "email": BOT_SERVICE_EMAIL,
            "org_id": body.org_id,
            "role": ROLE_ADMIN,
        },
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "org_id": body.org_id,
        "role": ROLE_ADMIN,
    }


@router.post("/switch-organisation", response_model=UserLoginResponse)
async def switch_organisation(
    body: SwitchOrganisationRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Issue a new JWT scoped to another organisation the user belongs to."""
    result = user_service.switch_organisation(current_user["email"], body.org_id)
    if result["status"] == "fail":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"],
        )
    return result


@router.get("/organisations", response_model=dict[str, Any])
async def list_organisations(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """List organisations the authenticated user belongs to."""
    result = user_service.list_organisations_for_user(current_user["email"])
    if result["status"] == "fail":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result["message"],
        )
    return result


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the authenticated user's profile for the active organisation."""
    profile = user_service.get_profile(
        current_user["email"],
        current_user.get("org_id"),
    )
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return profile


@router.get("/check/{email}", response_model=CheckEmailResponse)
async def check_user_join_eligibility(
    email: str,
    org_id: str | None = Query(
        None,
        description="Organisation id when checking invite eligibility",
    ),
) -> dict[str, Any]:
    """Public helper: whether an email exists and is already in the organisation."""
    return user_service.check_email_for_org(email, org_id)


@router.get("/{email}", response_model=UserResponse)
async def get_user(
    email: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Get user profile by email (self only)."""
    if current_user["email"] != email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this user's data",
        )

    profile = user_service.get_profile(email, current_user.get("org_id"))
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return profile


@router.post("/forgot-password", response_model=dict[str, Any])
async def forgot_password(request: ForgotPasswordRequest) -> dict[str, Any]:
    """Request a password-reset email (public)."""
    result = user_service.request_password_reset(request.email)
    if result["status"] == "fail":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"],
        )
    return result


@router.post("/reset-password", response_model=dict[str, Any])
async def reset_password(request: ResetPasswordRequest) -> dict[str, Any]:
    """Reset password using a reset token (public)."""
    result = user_service.reset_password_with_token(
        request.token,
        request.new_password,
    )
    if result["status"] == "fail":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"],
        )
    return result
