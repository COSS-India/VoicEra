"""Database connection for Mongo-compatible DB (FerretDB)."""

from __future__ import annotations

import logging

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from app.config import settings

logger = logging.getLogger(__name__)


class MongoDB:
    """Mongo-compatible connection manager (FerretDB / MongoDB wire protocol)."""

    client: MongoClient | None = None
    database: Database | None = None


mongodb = MongoDB()


def connect_to_mongo() -> None:
    """Create and verify the database connection."""
    try:
        mongodb.client = MongoClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=5000,
        )
        mongodb.client.admin.command("ping")
        mongodb.database = mongodb.client[settings.MONGODB_DATABASE]
        logger.info("Connected to Mongo-compatible DB (FerretDB) successfully")
    except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
        logger.error("Failed to connect to Mongo-compatible DB: %s", exc)
        raise


def close_mongo_connection() -> None:
    """Close the database connection if open."""
    if mongodb.client is not None:
        mongodb.client.close()
        mongodb.client = None
        mongodb.database = None
        logger.info("Disconnected from Mongo-compatible DB")


def get_database() -> Database:
    """Return the active database, connecting lazily if needed."""
    if mongodb.database is None:
        connect_to_mongo()
    assert mongodb.database is not None
    return mongodb.database


def ping_database() -> bool:
    """Return True if the server responds to ping."""
    if mongodb.client is None:
        return False
    try:
        mongodb.client.admin.command("ping")
        return True
    except Exception:
        return False
