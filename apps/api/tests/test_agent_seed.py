"""Default demo agents seeded into a newly created organisation."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pymongo.errors import BulkWriteError

from app.services import agent_seed
from app.services.agent_seed import DefaultAgentTemplateError


@pytest.fixture(autouse=True)
def _reset_templates():
    agent_seed.templates.cache_clear()
    yield
    agent_seed.templates.cache_clear()


class _FakeAgents:
    """Minimal stand-in for the Agents collection with a unique (org_id, name)."""

    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []

    def insert_many(self, docs: list[dict[str, Any]], ordered: bool = True):
        existing = {(d["org_id"], d["name"]) for d in self.docs}
        inserted, errors = [], []
        for index, doc in enumerate(docs):
            key = (doc["org_id"], doc["name"])
            if key in existing:
                errors.append({"index": index, "code": 11000, "errmsg": "duplicate key"})
                continue
            existing.add(key)
            self.docs.append(doc)
            inserted.append(doc["agent_id"])
        if errors:
            raise BulkWriteError({"writeErrors": errors})
        return MagicMock(inserted_ids=inserted)


def _db_with(collection: Any) -> MagicMock:
    db = MagicMock()
    db.__getitem__.return_value = collection
    return db


def test_bundled_templates_are_valid():
    """The shipped JSON must survive the same validation a user's agent gets."""
    loaded = agent_seed.templates()
    assert loaded, "expected at least one bundled template"
    for payload in loaded:
        assert payload.agent_category == "websocket"
        assert payload.config.knowledge_base.enabled is False
        assert payload.config.prompts.greeting_message.strip()
    assert len({p.name for p in loaded}) == len(loaded), "template names must be unique"


def test_seed_inserts_every_template():
    agents = _FakeAgents()
    with patch("app.services.agent_seed.get_database", return_value=_db_with(agents)):
        inserted = agent_seed.seed_default_agents("org-1", "owner@example.com")

    assert inserted == len(agent_seed.templates())
    assert {d["org_id"] for d in agents.docs} == {"org-1"}
    assert {d["created_by"] for d in agents.docs} == {"owner@example.com"}
    assert all(d["agent_category"] == "websocket" for d in agents.docs)
    assert all(d["telephony"] is None for d in agents.docs)
    assert len({d["agent_id"] for d in agents.docs}) == len(agents.docs)


def test_seeding_twice_is_idempotent():
    agents = _FakeAgents()
    with patch("app.services.agent_seed.get_database", return_value=_db_with(agents)):
        first = agent_seed.seed_default_agents("org-1", "owner@example.com")
        second = agent_seed.seed_default_agents("org-1", "owner@example.com")

    assert first == len(agent_seed.templates())
    assert second == 0
    assert len(agents.docs) == first


def test_non_duplicate_write_error_is_raised():
    """A real write failure must not be swallowed into a silent empty list."""
    collection = MagicMock()
    collection.insert_many.side_effect = BulkWriteError(
        {"writeErrors": [{"index": 0, "code": 121, "errmsg": "validation failed"}]}
    )
    with patch("app.services.agent_seed.get_database", return_value=_db_with(collection)):
        with pytest.raises(BulkWriteError):
            agent_seed.seed_default_agents("org-1", "owner@example.com")


@pytest.mark.parametrize(
    "template, expected",
    [
        ({"name": "T", "agent_category": "telephony"}, "websocket"),
        ({"name": "T", "knowledge_base": True}, "knowledge_base"),
        ({"name": "T", "provider": "not-a-provider"}, "not-a-provider"),
    ],
    ids=["telephony-category", "knowledge-base-enabled", "unknown-provider"],
)
def test_bad_template_fails_at_load(tmp_path, template, expected):
    base = json.loads(agent_seed.TEMPLATES_PATH.read_text(encoding="utf-8"))[0]
    entry = json.loads(json.dumps(base))
    entry["name"] = template["name"]
    if "agent_category" in template:
        entry["agent_category"] = template["agent_category"]
        entry["telephony_provider"] = "plivo"
    if template.get("knowledge_base"):
        entry["config"]["knowledge_base"] = {"enabled": True, "document_ids": ["doc-1"]}
    if "provider" in template:
        entry["config"]["models"]["llm_config"]["provider"] = template["provider"]

    path = tmp_path / "default_agents.json"
    path.write_text(json.dumps([entry]), encoding="utf-8")

    with patch.object(agent_seed, "TEMPLATES_PATH", path):
        agent_seed.templates.cache_clear()
        with pytest.raises(DefaultAgentTemplateError) as exc:
            agent_seed.validate_templates()
    assert expected in str(exc.value)


def test_missing_template_file_fails_at_load(tmp_path):
    with patch.object(agent_seed, "TEMPLATES_PATH", tmp_path / "nope.json"):
        agent_seed.templates.cache_clear()
        with pytest.raises(DefaultAgentTemplateError):
            agent_seed.validate_templates()


# --- the signup hook ---


def _signup(monkeypatch, *, enabled: bool, seed_side_effect=None):
    from app.models.schemas import UserCreate
    from app.services import user_service

    monkeypatch.setattr(user_service.settings, "SANDBOX_SEED_AGENTS", enabled)
    seed = MagicMock(return_value=2, side_effect=seed_side_effect)

    db = MagicMock()
    # No pre-existing Users row: signup takes the "new account" branch.
    db.__getitem__.return_value.find_one.return_value = None

    with (
        patch("app.services.user_service.get_database", return_value=db),
        patch(
            "app.services.user_service.org_service.create_organisation",
            return_value={"org_id": "org-1"},
        ),
        patch(
            "app.services.user_service._auth_success_response",
            return_value={"status": "success"},
        ),
        patch("app.services.user_service.agent_seed.seed_default_agents", seed),
    ):
        result = user_service.sign_up_user(
            UserCreate(
                email="owner@example.com",
                password="hunter2hunter2",
                organisation_name="Acme",
            )
        )
    return result, seed


def test_signup_does_not_seed_when_flag_is_off(monkeypatch):
    result, seed = _signup(monkeypatch, enabled=False)
    assert result["status"] == "success"
    seed.assert_not_called()


def test_signup_seeds_when_flag_is_on(monkeypatch):
    result, seed = _signup(monkeypatch, enabled=True)
    assert result["status"] == "success"
    seed.assert_called_once_with("org-1", "owner@example.com")


def test_signup_survives_a_seeding_failure(monkeypatch):
    result, seed = _signup(
        monkeypatch,
        enabled=True,
        seed_side_effect=RuntimeError("mongo is on fire"),
    )
    assert result["status"] == "success"
    seed.assert_called_once()
