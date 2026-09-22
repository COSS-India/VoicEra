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

from app.database import get_database
from apps.providers.cloud.groq.catalog import DEFAULT_LLM_MODEL

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

RETIRED_MODEL = "llama-3.3-70b-versatile"
COLLECTION = "Agents"


def migrate(dry_run: bool = False, assume_yes: bool = False) -> int:
    """Remap Agents with config.models.llm_config.provider=groq and
    model=RETIRED_MODEL to DEFAULT_LLM_MODEL.

    Returns the number of documents matched (updated, unless dry_run).
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

    if not dry_run and matches:
        if not assume_yes:
            reply = input(f"Update {len(matches)} agent(s) above? [y/N] ")
            if reply.strip().lower() not in ("y", "yes"):
                logger.info("Aborted, no changes made.")
                return 0
        collection.update_many(
            query, {"$set": {"config.models.llm_config.model": DEFAULT_LLM_MODEL}}
        )

    logger.info(
        "%s %d agent(s) (groq %s -> %s)",
        "Would migrate" if dry_run else "Migrated",
        len(matches),
        RETIRED_MODEL,
        DEFAULT_LLM_MODEL,
    )
    return len(matches)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="List affected agents without writing"
    )
    parser.add_argument(
        "--yes", action="store_true", help="Skip the confirmation prompt"
    )
    args = parser.parse_args()
    migrate(dry_run=args.dry_run, assume_yes=args.yes)
