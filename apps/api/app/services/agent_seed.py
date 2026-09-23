"""Seed demo agents into a newly created organisation.

Sandbox deployments set ``SANDBOX_SEED_AGENTS`` so signup lands on a usable
agent instead of an empty list and a provider-configuration wizard.

Templates live in ``app/seed/default_agents.json`` so a greeting or system
prompt can be retuned without a code change. They are parsed and validated
through the same path as a user-created agent, at import time — a template that
drifts from the provider registry fails the API's startup rather than a user's
signup.
"""

from __future__ import annotations

import json
import logging
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from pymongo.errors import BulkWriteError

from app.database import get_database
from app.models.schemas import AgentCreateRequest
from app.services.agent_config_validation import (
    AgentConfigValidationError,
    validate_agent_config,
)
from app.services.agent_service import COLLECTION, build_agent_document

logger = logging.getLogger(__name__)

TEMPLATES_PATH = Path(__file__).resolve().parents[1] / "seed" / "default_agents.json"

_DUPLICATE_KEY = 11000


class DefaultAgentTemplateError(ValueError):
    """Raised when a bundled template is not a valid agent."""


@lru_cache(maxsize=1)
def templates() -> tuple[AgentCreateRequest, ...]:
    """Parse and validate the bundled templates once per process."""
    try:
        raw = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DefaultAgentTemplateError(f"{TEMPLATES_PATH}: {exc}") from exc

    if not isinstance(raw, list):
        raise DefaultAgentTemplateError(f"{TEMPLATES_PATH}: expected a JSON list of agents")

    parsed: list[AgentCreateRequest] = []
    for index, entry in enumerate(raw):
        try:
            payload = AgentCreateRequest.model_validate(entry)
        except Exception as exc:
            raise DefaultAgentTemplateError(f"{TEMPLATES_PATH}[{index}]: {exc}") from exc

        if payload.agent_category != "websocket":
            raise DefaultAgentTemplateError(
                f"{TEMPLATES_PATH}[{index}]: default agents must be 'websocket' — a "
                "telephony template would provision against a provider the new "
                "organisation has not connected"
            )
        if payload.config.knowledge_base.enabled:
            raise DefaultAgentTemplateError(
                f"{TEMPLATES_PATH}[{index}]: knowledge_base must be disabled — a "
                "seeded agent cannot reference documents of an org created seconds ago"
            )
        try:
            # org_id=None keeps this database-free: it is the only argument
            # that reaches the knowledge-base branch of the validator.
            validate_agent_config(payload.config, org_id=None)
        except AgentConfigValidationError as exc:
            raise DefaultAgentTemplateError(f"{TEMPLATES_PATH}[{index}]: {exc}") from exc
        parsed.append(payload)

    return tuple(parsed)


def validate_templates() -> None:
    """Fail startup on a broken template rather than at the first signup."""
    loaded = templates()
    logger.info("Default agent templates loaded: %s", ", ".join(t.name for t in loaded))


def seed_default_agents(org_id: str, created_by_email: str) -> int:
    """Insert the default agents for ``org_id``. Returns the number inserted."""
    docs = [
        build_agent_document(
            org_id,
            created_by_email,
            payload,
            agent_id=str(uuid.uuid4()),
        )
        for payload in templates()
    ]
    if not docs:
        return 0

    try:
        result = get_database()[COLLECTION].insert_many(docs, ordered=False)
        inserted = len(result.inserted_ids)
    except BulkWriteError as exc:
        errors = exc.details.get("writeErrors", []) if exc.details else []
        if not errors or any(err.get("code") != _DUPLICATE_KEY for err in errors):
            raise
        # Re-running signup for the same org: org_name_unique makes seeding
        # idempotent. Anything other than a duplicate name is a real failure.
        inserted = len(docs) - len(errors)

    logger.info("Seeded %s default agent(s) for org %s", inserted, org_id)
    return inserted
