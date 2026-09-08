"""User service: signup, login, profile, org switch, password reset."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.auth import create_access_token, get_password_hash, verify_password
from app.config import settings
from app.database import get_database
from app.database_init import ROLE_MEMBER, ROLE_SUPER_ADMIN
from app.models.schemas import UserCreate
from app.services import member_service, org_service
from app.services.email_service import send_password_reset_email

logger = logging.getLogger(__name__)


def _build_organisations_list(email: str) -> list[dict[str, Any]]:
    memberships = member_service.list_memberships_for_email(email)
    org_ids = [m["org_id"] for m in memberships if m.get("org_id")]
    orgs_by_id = org_service.get_organisations_by_ids(org_ids)
    result: list[dict[str, Any]] = []
    for membership in memberships:
        org_id = membership.get("org_id")
        if not org_id:
            continue
        org = orgs_by_id.get(org_id) or {}
        result.append(
            {
                "org_id": org_id,
                "name": org.get("name", ""),
                "role": membership.get("role", ROLE_MEMBER),
            }
        )
    return result


def _token_payload(email: str, org_id: str, role: str) -> dict[str, Any]:
    return {
        "sub": email,
        "email": email,
        "org_id": org_id,
        "role": role,
    }


def _auth_success_response(
    email: str,
    org_id: str,
    role: str,
    *,
    message: str,
    is_first_login: bool = False,
) -> dict[str, Any]:
    organisations = _build_organisations_list(email)
    access_token = create_access_token(
        data=_token_payload(email, org_id, role),
    )
    return {
        "status": "success",
        "message": message,
        "access_token": access_token,
        "token_type": "bearer",
        "org_id": org_id,
        "role": role,
        "organisations": organisations,
        "is_first_login": is_first_login,
    }


def _set_default_org(email: str, org_id: str) -> None:
    """Persist the user's preferred active organisation for future logins."""
    get_database()["Users"].update_one(
        {"email": email},
        {"$set": {"default_org_id": org_id}},
    )


def _set_last_login(email: str) -> None:
    """Record the timestamp of the user's most recent successful login."""
    get_database()["Users"].update_one(
        {"email": email},
        {"$set": {"last_logged_in_at": datetime.now(timezone.utc).isoformat()}},
    )


def _resolve_active_membership(
    email: str,
    user_doc: dict[str, Any],
) -> dict[str, Any] | None:
    """Pick membership for login: saved default_org_id if still valid, else oldest."""
    memberships = member_service.list_memberships_for_email(email)
    if not memberships:
        return None

    preferred = user_doc.get("default_org_id")
    if preferred:
        for membership in memberships:
            if membership.get("org_id") == preferred:
                return membership
    return memberships[0]


def check_email_for_org(email: str, org_id: str | None = None) -> dict[str, Any]:
    """Invite UI helper: whether email exists and is already in the org."""
    try:
        db = get_database()
        exists = db["Users"].find_one({"email": email}) is not None
        already_in_org = False
        if org_id:
            already_in_org = (
                db["Memberships"].find_one({"email": email, "org_id": org_id})
                is not None
            )
        return {
            "exists": exists,
            "already_in_org": already_in_org,
            "can_join": not already_in_org,
        }
    except Exception as exc:
        logger.error("Error checking email: %s", exc)
        return {"exists": False, "already_in_org": False, "can_join": True}


def auth_response_for_membership(
    email: str,
    org_id: str,
    role: str,
    *,
    message: str,
    is_first_login: bool = False,
) -> dict[str, Any]:
    """Issue a JWT after a membership change (join, switch, etc.)."""
    _set_default_org(email, org_id)
    _set_last_login(email)
    return _auth_success_response(
        email,
        org_id,
        role,
        message=message,
        is_first_login=is_first_login,
    )


def sign_up_user(user_data: UserCreate) -> dict[str, Any]:
    """
    Create a new organisation and attach the user as super_admin.

    One Users row per email globally. If the email already exists, verify the
    password and add a super_admin membership for the new org — the same
    account can belong to many organisations.
    """
    try:
        db = get_database()
        users = db["Users"]
        memberships = db["Memberships"]

        existing_user = users.find_one({"email": user_data.email})
        if existing_user:
            stored = existing_user.get("password")
            if not stored or not verify_password(user_data.password, stored):
                return {
                    "status": "fail",
                    "message": "That password doesn't match your existing account.",
                }

        now = datetime.now(timezone.utc).isoformat()
        org = org_service.create_organisation(
            name=user_data.organisation_name,
            created_by_email=user_data.email,
        )
        org_id = org["org_id"]

        if existing_user:
            users.update_one(
                {"email": user_data.email},
                {"$set": {"default_org_id": org_id, "last_logged_in_at": now}},
            )
            is_first_login = existing_user.get("last_logged_in_at") is None
        else:
            users.insert_one(
                {
                    "email": user_data.email,
                    "password": get_password_hash(user_data.password),
                    "created_at": now,
                    "default_org_id": org_id,
                    "last_logged_in_at": now,
                }
            )
            is_first_login = True

        memberships.insert_one(
            {
                "email": user_data.email,
                "org_id": org_id,
                "role": ROLE_SUPER_ADMIN,
                "created_at": now,
            }
        )

        logger.info(
            "User signed up as super_admin: %s org=%s (%s)",
            user_data.email,
            org_id,
            user_data.organisation_name,
        )
        return _auth_success_response(
            user_data.email,
            org_id,
            ROLE_SUPER_ADMIN,
            message="Organisation created successfully",
            is_first_login=is_first_login,
        )
    except Exception as exc:
        logger.error("Error creating user: %s", exc)
        return {"status": "fail", "message": f"Error creating user: {exc}"}


def validate_user_and_get_token(email: str, password: str) -> dict[str, Any]:
    """Validate credentials and return a JWT for the user's default organisation."""
    try:
        user = get_database()["Users"].find_one({"email": email})
        if not user:
            return {"status": "fail", "message": "User not found"}

        stored = user.get("password")
        if not stored or not verify_password(password, stored):
            return {"status": "fail", "message": "Invalid password"}

        active = _resolve_active_membership(email, user)
        if not active:
            return {
                "status": "fail",
                "message": "User has no organisation memberships",
            }

        org_id = active["org_id"]
        role = active.get("role", ROLE_MEMBER)
        is_first_login = user.get("last_logged_in_at") is None
        # Keep default in sync when falling back to oldest membership
        if user.get("default_org_id") != org_id:
            _set_default_org(email, org_id)
        _set_last_login(email)
        return _auth_success_response(
            email,
            org_id,
            role,
            message="User authenticated successfully",
            is_first_login=is_first_login,
        )
    except Exception as exc:
        logger.error("Error validating user: %s", exc)
        return {"status": "fail", "message": f"Error validating user: {exc}"}


def switch_organisation(email: str, org_id: str) -> dict[str, Any]:
    """Issue a new JWT scoped to a different organisation the user belongs to."""
    try:
        membership = member_service.get_membership(email, org_id)
        if not membership:
            return {
                "status": "fail",
                "message": "Not a member of this organization",
            }
        role = membership.get("role", ROLE_MEMBER)
        _set_default_org(email, org_id)
        return _auth_success_response(
            email,
            org_id,
            role,
            message="Organisation switched successfully",
        )
    except Exception as exc:
        logger.error("Error switching organisation: %s", exc)
        return {"status": "fail", "message": f"Error switching organisation: {exc}"}


def delete_active_organisation(
    email: str,
    org_id: str,
    role: str,
) -> dict[str, Any]:
    """
    Super-admin deletes an organisation.

    Removes all memberships for that org; user accounts are preserved.
    """
    try:
        if role != ROLE_SUPER_ADMIN:
            return {
                "status": "fail",
                "message": "Only super admins can delete an organisation",
            }

        membership = member_service.get_membership(email, org_id)
        if not membership or membership.get("role") != ROLE_SUPER_ADMIN:
            return {
                "status": "fail",
                "message": "Only a super admin of this organisation can delete it",
            }

        result = org_service.delete_organisation(org_id)
        if result["status"] == "fail":
            return result

        remaining = _build_organisations_list(email)
        if not remaining:
            return {
                "status": "success",
                "message": result["message"],
                "org_id": None,
                "role": None,
                "access_token": None,
                "token_type": None,
                "organisations": [],
            }

        next_org = remaining[0]
        _set_default_org(email, next_org["org_id"])
        return _auth_success_response(
            email,
            next_org["org_id"],
            next_org["role"],
            message=result["message"],
        )
    except Exception as exc:
        logger.error("Error deleting organisation for %s: %s", email, exc)
        return {"status": "fail", "message": f"Error deleting organisation: {exc}"}


def get_profile(email: str, active_org_id: str | None) -> dict[str, Any] | None:
    """Build profile for /users/me using the JWT active org."""
    try:
        user = get_database()["Users"].find_one({"email": email})
        if not user:
            return None

        organisations = _build_organisations_list(email)
        if not organisations:
            return {
                "email": email,
                "org_id": active_org_id or "",
                "role": ROLE_MEMBER,
                "organisation_name": None,
                "organisations": [],
                "created_at": user.get("created_at"),
            }

        active = None
        if active_org_id:
            active = next(
                (o for o in organisations if o["org_id"] == active_org_id),
                None,
            )
        if active is None:
            active = organisations[0]

        return {
            "email": email,
            "org_id": active["org_id"],
            "role": active["role"],
            "organisation_name": active.get("name"),
            "organisations": organisations,
            "created_at": user.get("created_at"),
        }
    except Exception as exc:
        logger.error("Error building profile: %s", exc)
        return None


def list_organisations_for_user(email: str) -> dict[str, Any]:
    """Return organisations for the authenticated user."""
    try:
        organisations = _build_organisations_list(email)
        return {
            "status": "success",
            "organisations": organisations,
            "count": len(organisations),
        }
    except Exception as exc:
        logger.error("Error listing organisations: %s", exc)
        return {"status": "fail", "message": f"Error listing organisations: {exc}"}


def request_password_reset(email: str) -> dict[str, Any]:
    """Generate a reset token and send the password-reset email."""
    try:
        db = get_database()
        users = db["Users"]
        user = users.find_one({"email": email})
        if not user:
            return {
                "status": "success",
                "message": "If user exists, password reset email has been sent",
            }

        reset_token = str(uuid.uuid4())
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        users.update_one(
            {"email": email},
            {
                "$set": {
                    "reset_token": reset_token,
                    "reset_token_expires": expires_at,
                    "reset_token_used": False,
                }
            },
        )

        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"
        if send_password_reset_email(email, reset_token, reset_url):
            logger.info("Password reset email sent to: %s", email)
            return {
                "status": "success",
                "message": "Password reset email has been sent",
            }

        logger.warning("Failed to send password reset email to: %s", email)
        return {
            "status": "fail",
            "message": "Failed to send password reset email. Please try again.",
        }
    except Exception as exc:
        logger.error("Error generating reset token: %s", exc)
        return {"status": "fail", "message": f"Error: {exc}"}


def reset_password_with_token(token: str, new_password: str) -> dict[str, Any]:
    """Reset password using a previously issued reset token."""
    try:
        users = get_database()["Users"]
        user = users.find_one({"reset_token": token, "reset_token_used": False})
        if not user:
            return {"status": "fail", "message": "Invalid or expired reset token"}

        expires_raw = user.get("reset_token_expires")
        expires_at = datetime.fromisoformat(expires_raw)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            return {"status": "fail", "message": "Reset token has expired"}

        users.update_one(
            {"email": user.get("email")},
            {
                "$set": {
                    "password": get_password_hash(new_password),
                    "reset_token_used": True,
                }
            },
        )
        logger.info("Password reset successfully for: %s", user.get("email"))
        return {"status": "success", "message": "Password reset successfully"}
    except Exception as exc:
        logger.error("Error resetting password: %s", exc)
        return {"status": "fail", "message": f"Error: {exc}"}
