"""Campaign hard-delete cascades contact CSV purge (DPDP)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.campaign import campaign_deletion as deletion
from app.services.campaign import campaign_repository as repo
from app.services.campaign.campaign_repository import CampaignNotFoundError


@pytest.fixture(autouse=True)
def _fake_db(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    campaigns: dict[str, dict[str, Any]] = {}
    queued: dict[str, dict[str, Any]] = {}

    class FakeCampaigns:
        def insert_one(self, doc: dict[str, Any]) -> None:
            campaigns[doc["campaign_id"]] = dict(doc)

        def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
            doc = campaigns.get(query.get("campaign_id", ""))
            if not doc:
                return None
            if "org_id" in query and doc.get("org_id") != query["org_id"]:
                return None
            return dict(doc)

        def delete_one(self, query: dict[str, Any]) -> MagicMock:
            cid = query.get("campaign_id")
            result = MagicMock()
            if cid and cid in campaigns:
                del campaigns[cid]
                result.deleted_count = 1
            else:
                result.deleted_count = 0
            return result

        def count_documents(self, query: dict[str, Any]) -> int:
            source_id = query.get("source_id")
            return sum(1 for d in campaigns.values() if d.get("source_id") == source_id)

    class FakeQueued:
        def insert_many(self, docs: list[dict[str, Any]]) -> None:
            for doc in docs:
                queued[doc["queued_run_id"]] = dict(doc)

        def delete_many(self, query: dict[str, Any]) -> MagicMock:
            cid = query.get("campaign_id")
            remove = [k for k, d in queued.items() if d.get("campaign_id") == cid]
            for k in remove:
                del queued[k]
            result = MagicMock()
            result.deleted_count = len(remove)
            return result

    fake_db = {
        "Campaigns": FakeCampaigns(),
        "QueuedRuns": FakeQueued(),
        "Organizations": MagicMock(),
    }
    monkeypatch.setattr(repo, "get_database", lambda: fake_db)
    return {"campaigns": campaigns, "queued": queued}


def test_delete_purges_csv_when_sole_owner() -> None:
    camp = repo.create_campaign(
        {
            "org_id": "org-1",
            "name": "Solo",
            "agent_id": "agent-1",
            "source_id": "campaigns/org-1/solo.csv",
        }
    )
    cid = camp["campaign_id"]
    repo.bulk_create_queued_runs(
        [
            {
                "campaign_id": cid,
                "source_uuid": "row_1",
                "context_variables": {"phone_number": "+14155550001"},
            }
        ]
    )

    with patch.object(deletion, "MinIOStorage") as storage_cls:
        storage_cls.return_value.remove_object = MagicMock()
        summary = deletion.delete_campaign_for_org(
            org_id="org-1",
            campaign_id=cid,
            actor="admin@example.com",
        )

    assert summary["event"] == "campaign_deleted"
    assert summary["campaign_id"] == cid
    assert summary["actor"] == "admin@example.com"
    assert summary["source_id"] == "campaigns/org-1/solo.csv"
    assert summary["queued_runs_deleted"] == 1
    assert summary["source_object_purged"] is True
    assert "phone" not in str(summary).lower()
    storage_cls.return_value.remove_object.assert_called_once()
    assert repo.get_campaign_by_id(cid) is None


def test_delete_keeps_csv_when_shared_with_redial_child() -> None:
    source = "campaigns/org-1/shared.csv"
    parent = repo.create_campaign(
        {
            "org_id": "org-1",
            "name": "Parent",
            "agent_id": "agent-1",
            "source_id": source,
        }
    )
    child = repo.create_campaign(
        {
            "org_id": "org-1",
            "name": "Redial",
            "agent_id": "agent-1",
            "source_id": source,
        }
    )

    with patch.object(deletion, "MinIOStorage") as storage_cls:
        storage_cls.return_value.remove_object = MagicMock()
        summary = deletion.delete_campaign_for_org(
            org_id="org-1",
            campaign_id=parent["campaign_id"],
            actor="admin@example.com",
        )

    assert summary["source_object_purged"] is False
    storage_cls.return_value.remove_object.assert_not_called()
    assert repo.get_campaign_by_id(child["campaign_id"]) is not None

    with patch.object(deletion, "MinIOStorage") as storage_cls:
        storage_cls.return_value.remove_object = MagicMock()
        last = deletion.delete_campaign_for_org(
            org_id="org-1",
            campaign_id=child["campaign_id"],
            actor="admin@example.com",
        )

    assert last["source_object_purged"] is True
    storage_cls.return_value.remove_object.assert_called_once()


def test_delete_missing_campaign_raises() -> None:
    with pytest.raises(CampaignNotFoundError):
        deletion.delete_campaign_for_org(
            org_id="org-1",
            campaign_id="missing",
            actor="admin@example.com",
        )


def test_delete_route_cascades() -> None:
    """Route wires through delete_campaign_for_org."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.auth import get_current_user
    from app.routers import campaign as campaign_router

    app = FastAPI()
    app.include_router(campaign_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {
        "email": "admin@example.com",
        "org_id": "org-1",
        "role": "admin",
    }
    client = TestClient(app)

    with patch(
        "app.routers.campaign.delete_campaign_for_org",
        return_value={"event": "campaign_deleted"},
    ) as delete_fn:
        response = client.delete("/api/v1/campaign/camp-1")

    assert response.status_code == 200
    delete_fn.assert_called_once_with(
        org_id="org-1",
        campaign_id="camp-1",
        actor="admin@example.com",
    )
