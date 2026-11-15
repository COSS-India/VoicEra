"""Campaign contacts: one entry per CSV row with its calls and status."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import mongomock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import campaign as campaign_router
from app.services.campaign import campaign_contacts_service as contacts
from app.services.campaign import campaign_repository as repo
from app.services.campaign.sources.csv import CSVSyncService

CAMPAIGN = "camp-1"


@pytest.fixture()
def db(monkeypatch):
    database = mongomock.MongoClient()["voicera_test"]
    monkeypatch.setattr(repo, "get_database", lambda: database)
    monkeypatch.setattr(contacts, "get_database", lambda: database)
    database["Campaigns"].insert_one(
        {"campaign_id": CAMPAIGN, "org_id": "org-1", "name": "KKB wk46", "state": "running"}
    )
    return database


def _root(db, row: int) -> dict[str, Any]:
    return db["QueuedRuns"].find_one(
        {"campaign_id": CAMPAIGN, "source_uuid": f"csv_abc_row_{row}"}
    )


def _call(db, call_id: str, status: str, response: str, *, org_id: str = "org-1") -> None:
    db["CallLogs"].insert_one(
        {
            "call_id": call_id, "org_id": org_id, "campaign_id": CAMPAIGN,
            "status": status, "call_response": response,
            "start_time_utc": "2026-11-15T10:00:00+00:00", "duration": 30.0,
        }
    )


def _dial(db, run: dict[str, Any], call_id: str, *, state: str = "processed") -> None:
    db["QueuedRuns"].update_one(
        {"queued_run_id": run["queued_run_id"]}, {"$set": {"state": state, "call_id": call_id}}
    )


def _retry(run: dict[str, Any], n: int) -> dict[str, Any]:
    return repo.create_queued_run(
        campaign_id=CAMPAIGN,
        source_uuid=f"{run['source_uuid']}_retry_{n}",
        context_variables={**run["context_variables"], "is_retry": True,
                           "retry_attempt": n, "retry_reason": "no_answer"},
        state="queued",
        retry_count=n,
        parent_queued_run_id=run["queued_run_id"],
    )


def _seed(db) -> None:
    people = ["Ravi", "Asha", "Imran", "Meena", "Kiran", "Sunil", "Divya", "Om"]
    runs = []
    for row, name in enumerate(people, 1):
        phone = "" if name == "Imran" else f"+91984500000{row}"
        run = {
            "campaign_id": CAMPAIGN,
            "source_uuid": f"csv_abc_row_{row}",
            "context_variables": {"phone_number": phone, "contact_name": name,
                                  "participant_id": f"P-{row}"},
            "state": "queued",
        }
        if not phone:
            run.update(state="invalid", invalid_reason="missing phone_number")
        runs.append(run)
    repo.bulk_create_queued_runs(runs)

    _dial(db, _root(db, 1), "A"); _call(db, "A", "completed", "answered")          # Ravi
    asha = _root(db, 2)
    _dial(db, asha, "B"); _call(db, "B", "completed", "no_answer")                  # Asha 1st
    asha_retry = _retry(asha, 1)
    _dial(db, asha_retry, "C"); _call(db, "C", "completed", "answered")             # Asha 2nd
    kiran = _root(db, 5)
    _dial(db, kiran, "D"); _call(db, "D", "completed", "busy"); _retry(kiran, 1)    # Kiran retrying
    _dial(db, _root(db, 6), "E", state="processing"); _call(db, "E", "ringing", "pending")  # Sunil
    db["QueuedRuns"].update_one({"source_uuid": "csv_abc_row_7"}, {"$set": {"state": "failed"}})  # Divya
    _dial(db, _root(db, 8), "F"); _call(db, "F", "completed", "no_answer")          # Om


def test_contacts_cover_every_row_with_its_calls(db):
    _seed(db)
    page = contacts.list_campaign_contacts("org-1", CAMPAIGN, limit=100)
    assert page["total"] == 8
    by_name = {c["variables"]["contact_name"]: c for c in page["contacts"]}
    assert [c["row"] for c in page["contacts"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert {name: c["status"] for name, c in by_name.items()} == {
        "Ravi": "completed",
        "Asha": "completed",
        "Imran": "invalid",
        "Meena": "pending",
        "Kiran": "retrying",
        "Sunil": "in_progress",
        "Divya": "failed",
        "Om": "unanswered",
    }
    asha = by_name["Asha"]
    assert asha["attempts"] == 2 and asha["last_call_id"] == "C"
    assert [(c["attempt"], c["call_id"], c["call_response"]) for c in asha["calls"]] == [
        (1, "B", "no_answer"), (2, "C", "answered"),
    ]
    assert asha["variables"] == {"phone_number": "+919845000002", "contact_name": "Asha",
                                 "participant_id": "P-2"}
    imran = by_name["Imran"]
    assert imran["phone_number"] is None and imran["invalid_reason"] == "missing phone_number"
    assert imran["attempts"] == 0 and imran["calls"] == []
    assert by_name["Kiran"]["attempts"] == 1
    assert by_name["Meena"]["last_call_id"] is None


def test_contacts_paginate_by_row(db):
    _seed(db)
    page = contacts.list_campaign_contacts("org-1", CAMPAIGN, limit=3, offset=2)
    assert [c["row"] for c in page["contacts"]] == [3, 4, 5]
    assert page["total"] == 8 and page["limit"] == 3 and page["offset"] == 2


def test_chain_of_retries_folds_into_one_contact(db):
    repo.bulk_create_queued_runs([{"campaign_id": CAMPAIGN, "source_uuid": "csv_abc_row_1",
                                   "context_variables": {"phone_number": "+910000000001"}}])
    run = _root(db, 1)
    for n, call_id in enumerate(["X1", "X2", "X3"]):
        if n:
            run = _retry(run, n)
        _dial(db, run, call_id)
        _call(db, call_id, "completed", "no_answer" if n < 2 else "answered")
    page = contacts.list_campaign_contacts("org-1", CAMPAIGN)
    assert page["total"] == 1
    only = page["contacts"][0]
    assert only["status"] == "completed" and [c["call_id"] for c in only["calls"]] == ["X1", "X2", "X3"]


def test_calls_from_another_org_are_not_joined(db):
    repo.bulk_create_queued_runs([{"campaign_id": CAMPAIGN, "source_uuid": "csv_abc_row_1",
                                   "context_variables": {"phone_number": "+910000000001"}}])
    _dial(db, _root(db, 1), "Z")
    _call(db, "Z", "completed", "answered", org_id="org-2")
    only = contacts.list_campaign_contacts("org-1", CAMPAIGN)["contacts"][0]
    assert only["status"] == "in_progress" and only["calls"][0]["call_response"] is None


def _client(org_id: str = "org-1") -> TestClient:
    app = FastAPI()
    app.include_router(campaign_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {
        "email": "a@example.com", "org_id": org_id, "role": "member",
    }
    return TestClient(app)


def test_contacts_route(db):
    _seed(db)
    res = _client().get(f"/api/v1/campaign/{CAMPAIGN}/contacts?limit=2")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 8 and [c["row"] for c in body["contacts"]] == [1, 2]
    assert body["contacts"][1]["calls"][1]["call_id"] == "C"
    assert _client("org-2").get(f"/api/v1/campaign/{CAMPAIGN}/contacts").status_code == 404
    assert _client().get("/api/v1/campaign/nope/contacts").status_code == 404
    assert _client().get(f"/api/v1/campaign/{CAMPAIGN}/contacts?limit=0").status_code == 422


@pytest.mark.asyncio
async def test_csv_import_keeps_rows_without_a_phone_as_invalid(db):
    db["Campaigns"].update_one({"campaign_id": CAMPAIGN}, {"$set": {"source_id": "x.csv"}})
    csv_rows = [
        ["phone_number", "contact_name", "participant_id"],
        ["+919845000001", "Ravi", "P-1"],
        ["", "Imran", "P-3"],
        ["  ", "Blank", "P-4"],
        ["+919845000004", "Meena", "P-5"],
    ]
    service = CSVSyncService()
    with patch.object(service, "_fetch_csv_data", AsyncMock(return_value=csv_rows)):
        dialable = await service.sync_source_data(CAMPAIGN)
    assert dialable == 2
    campaign = db["Campaigns"].find_one({"campaign_id": CAMPAIGN})
    assert campaign["total_rows"] == 2 and campaign["invalid_rows"] == 2

    claimed = repo.claim_queued_runs_for_processing(
        CAMPAIGN, scheduled_before=datetime.now(timezone.utc), limit=10
    )
    assert sorted(r["context_variables"]["contact_name"] for r in claimed) == ["Meena", "Ravi"]

    page = contacts.list_campaign_contacts("org-1", CAMPAIGN)
    assert [(c["row"], c["status"]) for c in page["contacts"]] == [
        (1, "in_progress"), (2, "invalid"), (3, "invalid"), (4, "in_progress"),
    ]
