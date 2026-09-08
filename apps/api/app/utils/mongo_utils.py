"""Helpers for preparing Mongo / FerretDB documents for JSON responses."""

from __future__ import annotations

from typing import Any

from bson import ObjectId


def convert_objectid_to_str(obj: Any) -> Any:
    """Recursively convert ObjectId values to strings."""
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, dict):
        return {key: convert_objectid_to_str(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [convert_objectid_to_str(item) for item in obj]
    return obj


def prepare_mongo_response(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """Prepare a single MongoDB document for a JSON response."""
    if doc is None:
        return None
    return convert_objectid_to_str(doc)


def prepare_mongo_response_list(
    docs: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Prepare a list of MongoDB documents for a JSON response."""
    if docs is None:
        return []
    return [convert_objectid_to_str(doc) for doc in docs]
