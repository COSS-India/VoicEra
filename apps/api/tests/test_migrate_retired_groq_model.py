"""Unit test for the retired-Groq-model backfill script."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from app.scripts.migrate_retired_groq_model import RETIRED_MODEL, migrate
from apps.providers.cloud.groq.catalog import DEFAULT_LLM_MODEL


class _FakeUpdateResult:
    """Stand-in for pymongo's UpdateResult — only what this script reads."""

    def __init__(self, modified_count: int) -> None:
        self.modified_count = modified_count


class _FakeCollection:
    """Just enough of pymongo's Collection for this script's two calls."""

    def __init__(
        self, docs: list[dict[str, Any]], *, modified_count_override: int | None = None
    ) -> None:
        self._docs = docs
        self._modified_count_override = modified_count_override
        self.update_many_calls: list[dict[str, Any]] = []

    def _matches(self, query: dict[str, Any], doc: dict[str, Any]) -> bool:
        for dotted_key, expected in query.items():
            if dotted_key == "_id" and isinstance(expected, dict) and "$in" in expected:
                if doc.get("_id") not in expected["$in"]:
                    return False
                continue
            value: Any = doc
            for part in dotted_key.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            if value != expected:
                return False
        return True

    def find(self, query: dict[str, Any], _projection: dict[str, Any]) -> list[dict[str, Any]]:
        return [doc for doc in self._docs if self._matches(query, doc)]

    def update_many(self, query: dict[str, Any], update: dict[str, Any]) -> _FakeUpdateResult:
        self.update_many_calls.append(query)
        modified = 0
        for doc in self._docs:
            if self._matches(query, doc):
                doc["config"]["models"]["llm_config"]["model"] = update["$set"][
                    "config.models.llm_config.model"
                ]
                modified += 1
        if self._modified_count_override is not None:
            modified = self._modified_count_override
        return _FakeUpdateResult(modified)


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
        count = migrate(dry_run=False, assume_yes=True)

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


def test_migrate_declining_confirmation_does_not_write() -> None:
    """A declined confirmation must be distinguishable from 'nothing
    matched' — the caller (__main__) exits non-zero only when this is None,
    not when it's a legitimate zero-match no-op."""
    docs = [_agent("groq", RETIRED_MODEL)]
    with patch(
        "app.scripts.migrate_retired_groq_model.get_database",
        return_value={"Agents": _FakeCollection(docs)},
    ), patch("builtins.input", return_value="n"):
        count = migrate(dry_run=False)

    assert count is None
    assert docs[0]["config"]["models"]["llm_config"]["model"] == RETIRED_MODEL


def test_migrate_eof_on_prompt_aborts_cleanly() -> None:
    """Run non-interactively (e.g. `docker compose exec` without -it),
    input() raises EOFError instead of blocking — this must abort cleanly
    like a declined confirmation, not crash with a traceback."""
    docs = [_agent("groq", RETIRED_MODEL)]
    with patch(
        "app.scripts.migrate_retired_groq_model.get_database",
        return_value={"Agents": _FakeCollection(docs)},
    ), patch("builtins.input", side_effect=EOFError):
        count = migrate(dry_run=False)

    assert count is None
    assert docs[0]["config"]["models"]["llm_config"]["model"] == RETIRED_MODEL


def test_migrate_targets_matched_ids_not_original_query() -> None:
    """update_many must be scoped to the exact _ids that were found and
    logged, not a re-run of the original query — otherwise an agent that
    starts matching the query between find() and update_many() gets
    silently modified without ever appearing in the log."""
    docs = [_agent("groq", RETIRED_MODEL), _agent("groq", RETIRED_MODEL)]
    docs[1]["_id"] = "agent-2"
    fake_collection = _FakeCollection(docs)
    with patch(
        "app.scripts.migrate_retired_groq_model.get_database",
        return_value={"Agents": fake_collection},
    ), patch("builtins.input", return_value="y"):
        migrate(dry_run=False)

    assert len(fake_collection.update_many_calls) == 1
    sent_query = fake_collection.update_many_calls[0]
    assert sent_query == {"_id": {"$in": [docs[0]["_id"], "agent-2"]}}


def test_migrate_reports_actual_modified_count() -> None:
    """The closing log/return value must reflect update_many's real
    modified_count, not len(matches) — overstating what happened hides a
    partial or failed write."""
    docs = [_agent("groq", RETIRED_MODEL), _agent("groq", RETIRED_MODEL)]
    docs[1]["_id"] = "agent-2"
    fake_collection = _FakeCollection(docs, modified_count_override=1)
    with patch(
        "app.scripts.migrate_retired_groq_model.get_database",
        return_value={"Agents": fake_collection},
    ), patch("builtins.input", return_value="y"):
        count = migrate(dry_run=False)

    assert count == 1


def test_migrate_assume_yes_skips_prompt() -> None:
    docs = [_agent("groq", RETIRED_MODEL)]
    with patch(
        "app.scripts.migrate_retired_groq_model.get_database",
        return_value={"Agents": _FakeCollection(docs)},
    ), patch("builtins.input", side_effect=AssertionError("should not prompt")):
        count = migrate(dry_run=False, assume_yes=True)

    assert count == 1
    assert docs[0]["config"]["models"]["llm_config"]["model"] == DEFAULT_LLM_MODEL
