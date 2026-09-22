"""Unit test for the retired-Groq-model backfill script."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from app.scripts.migrate_retired_groq_model import RETIRED_MODEL, migrate
from apps.providers.cloud.groq.catalog import DEFAULT_LLM_MODEL


class _FakeCollection:
    """Just enough of pymongo's Collection for this script's two calls."""

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def _matches(self, query: dict[str, Any], doc: dict[str, Any]) -> bool:
        for dotted_key, expected in query.items():
            value: Any = doc
            for part in dotted_key.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            if value != expected:
                return False
        return True

    def find(self, query: dict[str, Any], _projection: dict[str, Any]) -> list[dict[str, Any]]:
        return [doc for doc in self._docs if self._matches(query, doc)]

    def update_many(self, query: dict[str, Any], update: dict[str, Any]) -> None:
        for doc in self._docs:
            if self._matches(query, doc):
                doc["config"]["models"]["llm_config"]["model"] = update["$set"][
                    "config.models.llm_config.model"
                ]


def _agent(provider: str, model: str) -> dict[str, Any]:
    return {
        "_id": f"agent-{provider}-{model}",
        "org_id": "org-1",
        "name": "test agent",
        "config": {"models": {"llm_config": {"provider": provider, "model": model}}},
    }


def test_migrate_remaps_retired_groq_agents() -> None:
    docs = [
        _agent("groq", RETIRED_MODEL),
        _agent("groq", "gemma2-9b-it"),
        _agent("openai", RETIRED_MODEL),
    ]
    with patch(
        "app.scripts.migrate_retired_groq_model.get_database",
        return_value={"Agents": _FakeCollection(docs)},
    ):
        count = migrate(dry_run=False)

    assert count == 1
    assert docs[0]["config"]["models"]["llm_config"]["model"] == DEFAULT_LLM_MODEL
    assert docs[1]["config"]["models"]["llm_config"]["model"] == "gemma2-9b-it"
    assert docs[2]["config"]["models"]["llm_config"]["model"] == RETIRED_MODEL


def test_migrate_dry_run_does_not_write() -> None:
    docs = [_agent("groq", RETIRED_MODEL)]
    with patch(
        "app.scripts.migrate_retired_groq_model.get_database",
        return_value={"Agents": _FakeCollection(docs)},
    ):
        count = migrate(dry_run=True)

    assert count == 1
    assert docs[0]["config"]["models"]["llm_config"]["model"] == RETIRED_MODEL
