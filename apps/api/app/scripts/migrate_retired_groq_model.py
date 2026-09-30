"""One-off migration: remap agents pinned to Groq's retired
llama-3.3-70b-versatile model to the new default (openai/gpt-oss-120b).

llama-3.3-70b-versatile was dropped from apps/providers/cloud/groq/catalog.py
after Groq retired it (confirmed via a live 404). Agent model configs store
`config.models.llm_config.model` as free-form text with no catalog
validation, so any already-saved agent pinned to that string keeps loading
fine and only fails at actual inference time (Groq 400/404). This backfills
those documents.

Usage:
    python -m app.scripts.migrate_retired_groq_model [--dry-run] [--yes]
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.database import get_database
from apps.providers.cloud.groq.catalog import DEFAULT_LLM_MODEL

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

RETIRED_MODEL = "llama-3.3-70b-versatile"
COLLECTION = "Agents"


def migrate(dry_run: bool = False, assume_yes: bool = False) -> int | None:
    """Remap Agents with config.models.llm_config.provider=groq and
    model=RETIRED_MODEL to DEFAULT_LLM_MODEL.

    Returns the number of documents actually modified (or matched, in
    dry-run mode). Returns None if matches existed but the migration was
    aborted without writing (declined confirmation, or no interactive
    terminal to confirm on) — callers must treat that as a failure, not a
    no-op success.
    """
    collection = get_database()[COLLECTION]
    query = {
        "config.models.llm_config.provider": "groq",
        "config.models.llm_config.model": RETIRED_MODEL,
    }
    matches = list(collection.find(query, {"_id": 1, "org_id": 1, "name": 1}))
    for doc in matches:
        logger.info(
            "%s agent_id=%s org_id=%s name=%r",
            "Would update" if dry_run else "Updating",
            doc["_id"],
            doc.get("org_id"),
            doc.get("name"),
        )

    if dry_run:
        logger.info(
            "Would migrate %d agent(s) (groq %s -> %s)",
            len(matches),
            RETIRED_MODEL,
            DEFAULT_LLM_MODEL,
        )
        return len(matches)

    if not matches:
        logger.info("Migrated 0 agent(s) (groq %s -> %s)", RETIRED_MODEL, DEFAULT_LLM_MODEL)
        return 0

    if not assume_yes:
        try:
            reply = input(f"Update {len(matches)} agent(s) above? [y/N] ")
        except EOFError:
            logger.info("No interactive terminal to confirm on; aborting without --yes.")
            return None
        if reply.strip().lower() not in ("y", "yes"):
            logger.info("Aborted, no changes made.")
            return None

    matched_ids = [doc["_id"] for doc in matches]
    result = collection.update_many(
        {"_id": {"$in": matched_ids}},
        {"$set": {"config.models.llm_config.model": DEFAULT_LLM_MODEL}},
    )
    modified_count = result.modified_count
    if modified_count != len(matches):
        logger.info(
            "Migrated %d/%d agent(s) (groq %s -> %s) — modified count did not match "
            "documents found, investigate before assuming this is complete",
            modified_count,
            len(matches),
            RETIRED_MODEL,
            DEFAULT_LLM_MODEL,
        )
    else:
        logger.info(
            "Migrated %d agent(s) (groq %s -> %s)",
            modified_count,
            RETIRED_MODEL,
            DEFAULT_LLM_MODEL,
        )
    return modified_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="List affected agents without writing"
    )
    parser.add_argument(
        "--yes", action="store_true", help="Skip the confirmation prompt"
    )
    args = parser.parse_args()
    outcome = migrate(dry_run=args.dry_run, assume_yes=args.yes)
    sys.exit(1 if outcome is None else 0)
