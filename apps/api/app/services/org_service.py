"""Organisation lookup and creation helpers."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.database import get_database

logger = logging.getLogger(__name__)


def generate_org_id() -> str:
    """Return a short unique organisation id."""
    return str(uuid.uuid4()).replace("-", "")[:6]


def get_organisation(org_id: str) -> dict[str, Any] | None:
    """Fetch an organisation by id (without Mongo _id)."""
    try:
        org = get_database()["Organizations"].find_one({"org_id": org_id})
        if not org:
            return None
        org.pop("_id", None)
        return org
    except Exception as exc:
        logger.error("Error fetching organisation %s: %s", org_id, exc)
        return None


def create_organisation(
    *,
    name: str,
    created_by_email: str,
    org_id: str | None = None,
) -> dict[str, Any]:
    """Insert a new organisation document and return it."""
    db = get_database()
    resolved_id = org_id or generate_org_id()
    doc = {
        "org_id": resolved_id,
        "name": name,
        "created_by_email": created_by_email,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db["Organizations"].insert_one(doc)
    doc.pop("_id", None)
    return doc


def get_organisations_by_ids(org_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Return a map of org_id → organisation doc for the given ids."""
    if not org_ids:
        return {}
    try:
        cursor = get_database()["Organizations"].find({"org_id": {"$in": org_ids}})
        result: dict[str, dict[str, Any]] = {}
        for org in cursor:
            org.pop("_id", None)
            result[org["org_id"]] = org
        return result
    except Exception as exc:
        logger.error("Error fetching organisations: %s", exc)
        return {}


def delete_organisation(org_id: str) -> dict[str, Any]:
    """
    Delete an organisation and all of its memberships.

    User accounts are never deleted — members who belong to other orgs keep
    those memberships. Clears ``default_org_id`` when it pointed at this org.
    """
    try:
        db = get_database()
        org = db["Organizations"].find_one({"org_id": org_id})
        if not org:
            return {"status": "fail", "message": "Organization not found"}

        member_emails = [
            doc["email"]
            for doc in db["Memberships"].find({"org_id": org_id}, {"email": 1})
            if doc.get("email")
        ]

        db["Memberships"].delete_many({"org_id": org_id})
        db["Organizations"].delete_one({"org_id": org_id})

        if member_emails:
            db["Users"].update_many(
                {"email": {"$in": member_emails}, "default_org_id": org_id},
                {"$unset": {"default_org_id": ""}},
            )

        logger.info(
            "Deleted organisation %s (%s memberships removed)",
            org_id,
            len(member_emails),
        )
        return {
            "status": "success",
            "message": "Organisation deleted successfully",
            "org_id": org_id,
            "memberships_removed": len(member_emails),
        }
    except Exception as exc:
        logger.error("Error deleting organisation %s: %s", org_id, exc)
        return {"status": "fail", "message": f"Error deleting organisation: {exc}"}
