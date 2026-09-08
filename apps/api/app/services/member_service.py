"""Membership operations: invite, list, assign-admin, remove."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.auth import get_password_hash, verify_password
from app.database import get_database
from app.database_init import ROLE_ADMIN, ROLE_MEMBER, ROLE_SUPER_ADMIN
from app.models.schemas import AssignAdminRequest, MemberInvite, RemoveMemberRequest
from app.services import org_service

logger = logging.getLogger(__name__)


def get_membership(email: str, org_id: str) -> dict[str, Any] | None:
    """Return a membership document or None."""
    try:
        doc = get_database()["Memberships"].find_one({"email": email, "org_id": org_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return doc
    except Exception as exc:
        logger.error("Error fetching membership: %s", exc)
        return None


def list_memberships_for_email(email: str) -> list[dict[str, Any]]:
    """All memberships for a user, oldest first."""
    try:
        cursor = get_database()["Memberships"].find({"email": email}).sort("created_at", 1)
        rows: list[dict[str, Any]] = []
        for doc in cursor:
            doc.pop("_id", None)
            rows.append(doc)
        return rows
    except Exception as exc:
        logger.error("Error listing memberships for %s: %s", email, exc)
        return []


def count_super_admins(org_id: str) -> int:
    """Count super_admin memberships in an organisation."""
    return get_database()["Memberships"].count_documents(
        {"org_id": org_id, "role": ROLE_SUPER_ADMIN}
    )


def invite_member(
    invite: MemberInvite,
    caller_email: str,
    org_id: str,
    caller_role: str,
) -> dict[str, Any]:
    """Invite a user into the caller's active organisation (admin or super_admin)."""
    try:
        if caller_role not in {ROLE_SUPER_ADMIN, ROLE_ADMIN}:
            return {
                "status": "fail",
                "message": "Only admins and super admins can invite members",
            }

        if not org_service.get_organisation(org_id):
            return {"status": "fail", "message": "Organization not found"}

        db = get_database()
        users = db["Users"]
        memberships = db["Memberships"]

        if memberships.find_one({"email": invite.email, "org_id": org_id}):
            return {
                "status": "fail",
                "message": "User is already a member of this organization",
            }

        existing_user = users.find_one({"email": invite.email})
        now = datetime.now(timezone.utc).isoformat()

        if existing_user:
            stored = existing_user.get("password")
            if not stored or not verify_password(invite.password, stored):
                return {
                    "status": "fail",
                    "message": (
                        "That password doesn't match your existing account."
                    ),
                }
        else:
            users.insert_one(
                {
                    "email": invite.email,
                    "password": get_password_hash(invite.password),
                    "created_at": now,
                    "default_org_id": org_id,
                }
            )

        memberships.insert_one(
            {
                "email": invite.email,
                "org_id": org_id,
                "role": ROLE_MEMBER,
                "created_at": now,
            }
        )
        logger.info(
            "Invited %s to org %s (by %s)",
            invite.email,
            org_id,
            caller_email,
        )
        return {
            "status": "success",
            "message": "Member invited successfully",
            "org_id": org_id,
            "role": ROLE_MEMBER,
        }
    except Exception as exc:
        logger.error("Error inviting member: %s", exc)
        return {"status": "fail", "message": f"Error inviting member: {exc}"}


def join_organisation(email: str, password: str, org_id: str) -> dict[str, Any]:
    """Public self-serve join: create account or verify existing password, add member role."""
    try:
        if not org_service.get_organisation(org_id):
            return {"status": "fail", "message": "Organization not found"}

        db = get_database()
        users = db["Users"]
        memberships = db["Memberships"]

        if memberships.find_one({"email": email, "org_id": org_id}):
            return {
                "status": "fail",
                "message": "User is already a member of this organization",
            }

        existing_user = users.find_one({"email": email})
        now = datetime.now(timezone.utc).isoformat()
        is_new_user = existing_user is None

        if existing_user:
            stored = existing_user.get("password")
            if not stored or not verify_password(password, stored):
                return {
                    "status": "fail",
                    "message": "That password doesn't match your existing account.",
                }
        else:
            users.insert_one(
                {
                    "email": email,
                    "password": get_password_hash(password),
                    "created_at": now,
                    "default_org_id": org_id,
                }
            )

        memberships.insert_one(
            {
                "email": email,
                "org_id": org_id,
                "role": ROLE_MEMBER,
                "created_at": now,
            }
        )
        logger.info("User %s joined org %s via public join", email, org_id)
        return {
            "status": "success",
            "message": "Joined organisation successfully",
            "email": email,
            "org_id": org_id,
            "role": ROLE_MEMBER,
            "is_first_login": is_new_user,
        }
    except Exception as exc:
        logger.error("Error joining organisation: %s", exc)
        return {"status": "fail", "message": f"Error joining organisation: {exc}"}


def get_members_by_org(org_id: str) -> dict[str, Any]:
    """List memberships for an organisation."""
    try:
        members: list[dict[str, Any]] = []
        cursor = get_database()["Memberships"].find({"org_id": org_id}).sort(
            "created_at", 1
        )
        for doc in cursor:
            members.append(
                {
                    "email": doc.get("email"),
                    "role": doc.get("role", ROLE_MEMBER),
                    "created_at": doc.get("created_at"),
                }
            )
        return {"status": "success", "members": members, "count": len(members)}
    except Exception as exc:
        logger.error("Error fetching members: %s", exc)
        return {"status": "fail", "message": f"Error fetching members: {exc}"}


def assign_admin(
    request: AssignAdminRequest,
    caller_email: str,
    org_id: str,
    caller_role: str,
) -> dict[str, Any]:
    """Promote a member to admin (super_admin only)."""
    try:
        if caller_role != ROLE_SUPER_ADMIN:
            return {
                "status": "fail",
                "message": "Only super admins can assign admins",
            }

        if request.email == caller_email:
            return {"status": "fail", "message": "Cannot change your own role this way"}

        memberships = get_database()["Memberships"]
        target = memberships.find_one({"email": request.email, "org_id": org_id})
        if not target:
            return {"status": "fail", "message": "Member not found in this organization"}

        if target.get("role") == ROLE_SUPER_ADMIN:
            return {
                "status": "fail",
                "message": "Cannot change role of a super admin",
            }

        if target.get("role") == ROLE_ADMIN:
            return {"status": "success", "message": "User is already an admin"}

        memberships.update_one(
            {"email": request.email, "org_id": org_id},
            {"$set": {"role": ROLE_ADMIN}},
        )
        logger.info(
            "Assigned admin in org %s: %s (by %s)",
            org_id,
            request.email,
            caller_email,
        )
        return {"status": "success", "message": "Member promoted to admin"}
    except Exception as exc:
        logger.error("Error assigning admin: %s", exc)
        return {"status": "fail", "message": f"Error assigning admin: {exc}"}


def remove_member(
    request: RemoveMemberRequest,
    caller_email: str,
    org_id: str,
    caller_role: str,
) -> dict[str, Any]:
    """Remove a membership (super_admin only)."""
    try:
        if caller_role != ROLE_SUPER_ADMIN:
            return {
                "status": "fail",
                "message": "Only super admins can remove members",
            }

        if request.email == caller_email:
            return {"status": "fail", "message": "Cannot remove yourself"}

        db = get_database()
        memberships = db["Memberships"]
        target = memberships.find_one({"email": request.email, "org_id": org_id})
        if not target:
            return {"status": "fail", "message": "Member not found in this organization"}

        if target.get("role") == ROLE_SUPER_ADMIN:
            if count_super_admins(org_id) <= 1:
                return {
                    "status": "fail",
                    "message": "Cannot remove the last super admin",
                }

        result = memberships.delete_one({"email": request.email, "org_id": org_id})
        if result.deleted_count == 0:
            return {"status": "fail", "message": "Failed to remove member"}

        remaining = memberships.count_documents({"email": request.email})
        if remaining == 0:
            db["Users"].delete_one({"email": request.email})

        logger.info(
            "Removed %s from org %s (by %s)",
            request.email,
            org_id,
            caller_email,
        )
        return {"status": "success", "message": "Member removed successfully"}
    except Exception as exc:
        logger.error("Error removing member: %s", exc)
        return {"status": "fail", "message": f"Error removing member: {exc}"}
