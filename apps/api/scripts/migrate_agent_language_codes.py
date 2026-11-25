#!/usr/bin/env python3
"""Migrate agent language ids to BCP 47: od -> or, bh -> bhb.

Rewrites every document in the ``Agents`` collection via
``app.services.language_code_migration.migrate_agent_config``.

Usage (from repo root, with API env loaded)::

    PYTHONPATH=. python apps/api/scripts/migrate_agent_language_codes.py
    PYTHONPATH=. python apps/api/scripts/migrate_agent_language_codes.py --dry-run

Requires the same Mongo/FerretDB settings as the API (``MONGODB_URI``, etc.).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _API_ROOT.parent.parent
for path in (_REPO_ROOT, _API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.database import close_mongo_connection, connect_to_mongo, get_database  # noqa: E402
from app.services.language_code_migration import migrate_agent_config  # noqa: E402

logger = logging.getLogger("migrate_agent_language_codes")


def run(*, dry_run: bool) -> int:
    connect_to_mongo()
    db = get_database()
    agents = db["Agents"]
    scanned = 0
    updated = 0
    try:
        for doc in agents.find({}):
            scanned += 1
            agent_id = doc.get("agent_id") or doc.get("_id")
            new_config, changed = migrate_agent_config(doc.get("config"))
            if not changed:
                continue
            updated += 1
            logger.info(
                "%s agent_id=%s primary=%s models=%s",
                "DRY-RUN would update" if dry_run else "Updating",
                agent_id,
                (new_config.get("language") or {}).get("primary"),
                sorted((new_config.get("models") or {}).keys()),
            )
            if dry_run:
                continue
            agents.update_one({"_id": doc["_id"]}, {"$set": {"config": new_config}})
    finally:
        close_mongo_connection()

    logger.info(
        "Done. scanned=%s updated=%s dry_run=%s",
        scanned,
        updated,
        dry_run,
    )
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report agents that would change without writing.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
