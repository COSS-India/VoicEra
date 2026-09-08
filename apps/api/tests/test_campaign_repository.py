"""Campaign repository unit tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pymongo import ReturnDocument

from app.services.campaign import campaign_repository as repo


@pytest.fixture(autouse=True)
def _clear_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    campaigns: dict[str, dict[str, Any]] = {}
    queued: dict[str, dict[str, Any]] = {}

    class FakeCampaigns:
        def insert_one(self, doc: dict[str, Any]) -> None:
            campaigns[doc["campaign_id"]] = dict(doc)

        def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
            if "campaign_id" in query:
                doc = campaigns.get(query["campaign_id"])
                return dict(doc) if doc else None
            return None

        def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> MagicMock:
            doc = self.find_one(query)
            result = MagicMock()
            if not doc:
                result.matched_count = 0
                return result
            if "$set" in update:
                campaigns[doc["campaign_id"]].update(update["$set"])
            if "$push" in update:
                campaigns[doc["campaign_id"]].setdefault("logs", []).append(
                    update["$push"]["logs"]
                )
            result.matched_count = 1
            return result

        def find(self, query: dict[str, Any]) -> list[dict[str, Any]]:
            return [dict(v) for v in campaigns.values() if v.get("org_id") == query.get("org_id")]

    class FakeQueued:
        def __init__(self) -> None:
            self.docs: dict[str, dict[str, Any]] = queued

        def insert_many(self, docs: list[dict[str, Any]]) -> None:
            for doc in docs:
                self.docs[doc["queued_run_id"]] = dict(doc)

        def find_one_and_update(self, query, update, sort=None, return_document=None):
            for qid, doc in list(self.docs.items()):
                if doc.get("campaign_id") != query.get("campaign_id"):
                    continue
                if doc.get("state") != query.get("state"):
                    continue
                scheduled = doc.get("scheduled_for")
                if scheduled is not None:
                    before = query["$or"][1]["scheduled_for"]["$lte"]
                    if scheduled > before:
                        continue
                updated = dict(doc)
                updated.update(update["$set"])
                self.docs[qid] = updated
                return updated
            return None

        def update_many(self, query, update):
            count = 0
            for qid, doc in self.docs.items():
                if doc.get("queued_run_id") in query["queued_run_id"]["$in"]:
                    doc.update(update["$set"])
                    count += 1
            result = MagicMock()
            result.modified_count = count
            return result

        def count_documents(self, query: dict[str, Any]) -> int:
            total = 0
            for doc in self.docs.values():
                if doc.get("campaign_id") != query.get("campaign_id"):
                    continue
                if "state" in query and doc.get("state") != query["state"]:
                    continue
                total += 1
            return total

    fake_db = {
        "Campaigns": FakeCampaigns(),
        "QueuedRuns": FakeQueued(),
        "Organizations": MagicMock(),
    }

    def get_database():
        return fake_db

    monkeypatch.setattr(repo, "get_database", get_database)
    campaigns.clear()
    queued.clear()


def test_create_and_get_campaign() -> None:
    doc = repo.create_campaign(
        {
            "org_id": "org-1",
            "name": "Test",
            "agent_id": "agent-1",
            "source_id": "campaigns/org-1/file.csv",
        }
    )
    fetched = repo.get_campaign_by_id(doc["campaign_id"])
    assert fetched is not None
    assert fetched["state"] == "created"


def test_bulk_create_and_claim_queued_runs() -> None:
    campaign = repo.create_campaign(
        {
            "org_id": "org-1",
            "name": "Dial",
            "agent_id": "agent-1",
            "source_id": "campaigns/org-1/file.csv",
        }
    )
    cid = campaign["campaign_id"]
    repo.bulk_create_queued_runs(
        [
            {
                "campaign_id": cid,
                "source_uuid": "row_1",
                "context_variables": {"phone_number": "+14155550001"},
            },
            {
                "campaign_id": cid,
                "source_uuid": "row_2",
                "context_variables": {"phone_number": "+14155550002"},
            },
        ]
    )
    claimed = repo.claim_queued_runs_for_processing(
        cid,
        scheduled_before=datetime.now(timezone.utc),
        limit=1,
    )
    assert len(claimed) == 1
    assert claimed[0]["state"] == "processing"
