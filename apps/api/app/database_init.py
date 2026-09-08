"""Idempotent database initialization for auth collections and indexes."""

from __future__ import annotations

import logging
from typing import Any

from pymongo.collection import Collection
from pymongo.database import Database

from app.database import get_database

logger = logging.getLogger(__name__)

ROLE_SUPER_ADMIN = "super_admin"
ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
VALID_ROLES = frozenset({ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_MEMBER})


def _ensure_index(
    collection: Collection,
    keys: str | list[tuple[str, int]],
    *,
    name: str,
    unique: bool = False,
    **kwargs: Any,
) -> None:
    """Create an index if missing; ignore duplicate / already-exists errors."""
    try:
        collection.create_index(keys, unique=unique, name=name, **kwargs)
    except Exception as exc:
        message = str(exc).lower()
        if "already exists" not in message and "duplicate" not in message:
            logger.warning("Index creation warning on %s.%s: %s", collection.name, name, exc)


def _ensure_organizations(db: Database, existing: set[str]) -> None:
    if "Organizations" not in existing:
        logger.info("Creating Organizations collection")
    else:
        logger.debug("Organizations already exists; ensuring indexes")

    orgs = db["Organizations"]
    _ensure_index(orgs, "org_id", name="org_id_unique", unique=True)
    _ensure_index(orgs, "name", name="name_index")


def _ensure_users(db: Database, existing: set[str]) -> None:
    if "Users" not in existing:
        logger.info("Creating Users collection")
    else:
        logger.debug("Users already exists; ensuring indexes")

    users = db["Users"]
    _ensure_index(users, "email", name="email_unique", unique=True)


def _ensure_memberships(db: Database, existing: set[str]) -> None:
    if "Memberships" not in existing:
        logger.info("Creating Memberships collection")
    else:
        logger.debug("Memberships already exists; ensuring indexes")

    memberships = db["Memberships"]
    _ensure_index(
        memberships,
        [("email", 1), ("org_id", 1)],
        name="email_org_unique",
        unique=True,
    )
    _ensure_index(memberships, "org_id", name="org_id_index")
    _ensure_index(memberships, "email", name="email_index")


def _ensure_provider_auth(db: Database, existing: set[str]) -> None:
    if "ProviderAuth" not in existing:
        logger.info("Creating ProviderAuth collection")
    else:
        logger.debug("ProviderAuth already exists; ensuring indexes")

    provider_auth = db["ProviderAuth"]
    _ensure_index(
        provider_auth,
        [("org_id", 1), ("provider", 1)],
        name="org_provider_unique",
        unique=True,
    )
    _ensure_index(provider_auth, "org_id", name="org_id_index")


def _ensure_agents(db: Database, existing: set[str]) -> None:
    if "Agents" not in existing:
        logger.info("Creating Agents collection")
    else:
        logger.debug("Agents already exists; ensuring indexes")

    agents = db["Agents"]
    _ensure_index(
        agents,
        [("org_id", 1), ("agent_id", 1)],
        name="org_agent_id_unique",
        unique=True,
    )
    _ensure_index(
        agents,
        [("org_id", 1), ("name", 1)],
        name="org_name_unique",
        unique=True,
    )
    _ensure_index(agents, "org_id", name="org_id_index")
    _ensure_index(agents, "created_by", name="created_by_index")
    _ensure_index(
        agents,
        "linked_phone_number",
        name="linked_phone_number_index",
    )


def _ensure_phone_numbers(db: Database, existing: set[str]) -> None:
    if "PhoneNumbers" not in existing:
        logger.info("Creating PhoneNumbers collection")
    else:
        logger.debug("PhoneNumbers already exists; ensuring indexes")

    phones = db["PhoneNumbers"]
    _ensure_index(
        phones,
        "phone_number",
        name="phone_number_unique",
        unique=True,
    )
    _ensure_index(phones, "org_id", name="org_id_index")
    _ensure_index(phones, "agent_id", name="agent_id_index")
    _ensure_index(
        phones,
        [("org_id", 1), ("agent_id", 1)],
        name="org_agent_id_index",
    )
    _ensure_index(phones, "provider", name="provider_index")


def _ensure_knowledge_documents(db: Database, existing: set[str]) -> None:
    if "KnowledgeDocuments" not in existing:
        logger.info("Creating KnowledgeDocuments collection")
    else:
        logger.debug("KnowledgeDocuments already exists; ensuring indexes")

    docs = db["KnowledgeDocuments"]
    _ensure_index(
        docs,
        [("org_id", 1), ("document_id", 1)],
        name="org_document_id_unique",
        unique=True,
    )
    _ensure_index(
        docs,
        [("org_id", 1), ("created_at", -1)],
        name="org_created_at_index",
    )
    _ensure_index(
        docs,
        [("org_id", 1), ("status", 1)],
        name="org_status_index",
    )


def _ensure_call_logs(db: Database, existing: set[str]) -> None:
    if "CallLogs" not in existing:
        logger.info("Creating CallLogs collection")
    else:
        logger.debug("CallLogs already exists; ensuring indexes")

    call_logs = db["CallLogs"]
    _ensure_index(call_logs, "call_id", name="call_id_unique", unique=True)
    _ensure_index(
        call_logs,
        [("org_id", 1), ("created_at", -1)],
        name="org_created_at_index",
    )
    _ensure_index(
        call_logs,
        "provider_call_sid",
        name="provider_call_sid_index",
        sparse=True,
    )
    _ensure_index(
        call_logs,
        [("org_id", 1), ("agent_id", 1)],
        name="org_agent_id_index",
    )
    _ensure_index(
        call_logs,
        [("org_id", 1), ("campaign_id", 1), ("created_at", -1)],
        name="org_campaign_created_index",
        sparse=True,
    )


def _ensure_call_metrics(db: Database, existing: set[str]) -> None:
    if "CallMetrics" not in existing:
        logger.info("Creating CallMetrics collection")
    else:
        logger.debug("CallMetrics already exists; ensuring indexes")

    call_metrics = db["CallMetrics"]
    _ensure_index(call_metrics, "call_id", name="call_id_unique", unique=True)
    _ensure_index(
        call_metrics,
        [("org_id", 1), ("call_id", 1)],
        name="org_call_id_index",
    )


def _ensure_campaigns(db: Database, existing: set[str]) -> None:
    if "Campaigns" not in existing:
        logger.info("Creating Campaigns collection")
    campaigns = db["Campaigns"]
    _ensure_index(campaigns, "campaign_id", name="campaign_id_unique", unique=True)
    _ensure_index(
        campaigns,
        [("org_id", 1), ("created_at", -1)],
        name="org_created_at_index",
    )
    _ensure_index(
        campaigns,
        [("org_id", 1), ("state", 1)],
        name="org_state_index",
    )


def _ensure_queued_runs(db: Database, existing: set[str]) -> None:
    if "QueuedRuns" not in existing:
        logger.info("Creating QueuedRuns collection")
    queued = db["QueuedRuns"]
    _ensure_index(queued, "queued_run_id", name="queued_run_id_unique", unique=True)
    _ensure_index(
        queued,
        [("campaign_id", 1), ("state", 1), ("scheduled_for", 1)],
        name="campaign_state_scheduled_index",
    )
    _ensure_index(
        queued,
        [("campaign_id", 1), ("source_uuid", 1), ("retry_count", 1)],
        name="campaign_source_retry_unique",
        unique=True,
    )
    _ensure_index(
        queued,
        "call_id",
        name="call_id_index",
        sparse=True,
    )


def initialize_database() -> None:
    """
    Ensure auth collections and indexes exist.

    Safe to run on every startup (idempotent).
    """
    try:
        db = get_database()
        existing = set(db.list_collection_names())

        _ensure_organizations(db, existing)
        _ensure_users(db, existing)
        _ensure_memberships(db, existing)
        _ensure_provider_auth(db, existing)
        _ensure_agents(db, existing)
        _ensure_phone_numbers(db, existing)
        _ensure_knowledge_documents(db, existing)
        _ensure_call_logs(db, existing)
        _ensure_call_metrics(db, existing)
        _ensure_campaigns(db, existing)
        _ensure_queued_runs(db, existing)

        logger.info(
            "Database initialization completed "
            "(Organizations, Users, Memberships, ProviderAuth, Agents, "
            "PhoneNumbers, KnowledgeDocuments, CallLogs, CallMetrics, Campaigns, QueuedRuns)"
        )
    except Exception as exc:
        logger.error("Error initializing database: %s", exc)
        raise
