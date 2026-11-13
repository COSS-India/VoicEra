"""Call list filters and turn-by-turn transcripts."""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import httpx
import mongomock
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.config import settings
from app.routers import calls as calls_router
from app.services import call_log_service
from app.services import call_transcript_service as ts
from app.services import call_webhook_service as wh

TRANSCRIPT = (
    "call_id=call-1\n"
    "---\n"
    "[2026-11-13T10:00:01.000+00:00] assistant: Namaste, main Rozgar Hub se bol rahi hoon.\n"
    "[2026-11-13T10:00:05.500+00:00] user: Haan, boliye.\n"
    "[2026-11-13T10:00:07.000+00:00] assistant: Aapke liye do naukriyan hain:\n"
    "1. Driver, Hubli\n"
    "2. Delivery, Dharwad\n"
    "[2026-11-13T10:00:15.250+00:00] user: Pehli wali.\n"
)


# ------------------------------------------------------------ transcript ----


def test_parse_transcript_turns_and_continuation_lines():
    turns = ts.parse_transcript(TRANSCRIPT)
    assert [t["role"] for t in turns] == ["assistant", "user", "assistant", "user"]
    assert [t["speaker"] for t in turns] == ["agent", "caller", "agent", "caller"]
    assert [t["index"] for t in turns] == [0, 1, 2, 3]
    assert turns[1] == {
        "index": 1,
        "role": "user",
        "speaker": "caller",
        "timestamp": "2026-11-13T10:00:05.500+00:00",
        "text": "Haan, boliye.",
    }
    assert turns[2]["text"] == "Aapke liye do naukriyan hain:\n1. Driver, Hubli\n2. Delivery, Dharwad"


def test_parse_transcript_edge_cases():
    assert ts.parse_transcript("") == []
    assert ts.parse_transcript("call_id=x\n---\n") == []
    no_header = ts.parse_transcript("[t] user: hi\r\n[t] assistant: hello\r\n")
    assert [t["text"] for t in no_header] == ["hi", "hello"]
    # a line that only looks like a header before any turn is ignored
    assert ts.parse_transcript("stray line\n[t] user: x\n")[0]["text"] == "x"


class _Resp:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def close(self) -> None:
        pass

    def release_conn(self) -> None:
        pass


class _FakeStorage:
    def __init__(self, objects: dict[tuple[str, str], bytes]) -> None:
        self.objects = objects
        self.client = self

    def get_object(self, bucket: str, name: str) -> _Resp:
        if (bucket, name) not in self.objects:
            raise RuntimeError("NoSuchKey")
        return _Resp(self.objects[(bucket, name)])


def _call_doc(**extra) -> dict[str, Any]:
    doc = {
        "call_id": "call-1",
        "org_id": "org-1",
        "agent_id": "agent-1",
        "status": "completed",
        "call_response": "answered",
        "transcript_url": "minio://voicera-calls/org-1/call-1/transcript.txt",
    }
    doc.update(extra)
    return doc


def test_load_turns_reads_storage_and_reports_unavailable():
    storage = _FakeStorage({("voicera-calls", "org-1/call-1/transcript.txt"): TRANSCRIPT.encode()})
    assert len(ts.load_turns(_call_doc(), storage=storage)) == 4
    with pytest.raises(ts.TranscriptUnavailableError, match="no transcript"):
        ts.load_turns(_call_doc(transcript_url=None), storage=storage)
    with pytest.raises(ts.TranscriptUnavailableError, match="invalid"):
        ts.load_turns(_call_doc(transcript_url="s3://elsewhere"), storage=storage)
    with pytest.raises(ts.TranscriptUnavailableError, match="could not read"):
        ts.load_turns(_call_doc(call_id="c2", transcript_url="minio://voicera-calls/org-1/c2/t.txt"),
                      storage=storage)


# --------------------------------------------------------------- routes ----


@pytest.fixture()
def db():
    return mongomock.MongoClient()["voicera_test"]


def _client(org_id: str = "org-1") -> TestClient:
    app = FastAPI()
    app.include_router(calls_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {
        "email": "a@example.com", "org_id": org_id, "role": "member",
    }
    return TestClient(app)


def test_transcript_turns_route(db):
    db["CallLogs"].insert_many([_call_doc(), _call_doc(call_id="call-2", transcript_url=None)])
    storage = _FakeStorage({("voicera-calls", "org-1/call-1/transcript.txt"): TRANSCRIPT.encode()})
    with patch.object(call_log_service, "get_database", return_value=db), \
         patch.object(ts, "_new_storage", return_value=storage):
        client = _client()
        res = client.get("/api/v1/calls/call-1/transcript/turns")
        assert res.status_code == 200
        body = res.json()
        assert body["call_id"] == "call-1" and body["turn_count"] == 4
        assert body["turns"][3]["speaker"] == "caller"
        res = client.get("/api/v1/calls/call-2/transcript/turns")
        assert res.status_code == 404 and "no transcript" in res.json()["detail"]
        assert client.get("/api/v1/calls/missing/transcript/turns").status_code == 404
        assert _client("org-2").get("/api/v1/calls/call-1/transcript/turns").status_code == 404


def _seed_calls(db) -> None:
    base = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)
    rows = [
        ("c1", "org-1", "agent-a", "camp-1", "completed", "answered", "outbound", 0),
        ("c2", "org-1", "agent-a", "camp-1", "completed", "no_answer", "outbound", 1),
        ("c3", "org-1", "agent-a", "camp-2", "failed", "failed", "outbound", 2),
        ("c4", "org-1", "agent-b", None, "completed", "answered", "inbound", 3),
        ("c5", "org-1", "agent-b", None, "in_progress", "pending", "web", 4),
        ("x1", "org-2", "agent-a", "camp-1", "completed", "answered", "outbound", 0),
    ]
    for cid, org, agent, camp, status, response, ctype, hours in rows:
        doc = {
            "call_id": cid, "org_id": org, "agent_id": agent, "status": status,
            "call_response": response, "call_type": ctype,
            "from_number": "+910000000000", "to_number": "+919999999999",
            "created_at": (base + timedelta(hours=hours)).isoformat(),
        }
        if camp:
            doc["campaign_id"] = camp
        db["CallLogs"].insert_one(doc)


def _list(db, query: str = "", org_id: str = "org-1") -> httpx.Response:
    with patch.object(call_log_service, "get_database", return_value=db), \
         patch.object(calls_router.org_service, "get_organisation", return_value={"org_id": org_id}):
        return _client().get(f"/api/v1/calls/org/{org_id}{query}")


def _ids(res) -> list[str]:
    assert res.status_code == 200, res.text
    return [c["call_id"] for c in res.json()["calls"]]


def test_list_without_filters_is_unchanged(db):
    _seed_calls(db)
    res = _list(db)
    assert _ids(res) == ["c5", "c4", "c3", "c2", "c1"]  # newest first, org-scoped
    assert res.json()["total"] == 5


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("?agent_id=agent-a", ["c3", "c2", "c1"]),
        ("?campaign_id=camp-1", ["c2", "c1"]),
        ("?agent_id=agent-a&campaign_id=camp-2", ["c3"]),
        ("?status=completed", ["c4", "c2", "c1"]),
        ("?call_response=answered", ["c4", "c1"]),
        ("?call_type=inbound", ["c4"]),
        ("?created_from=2026-11-13T11:00:00Z", ["c5", "c4", "c3", "c2"]),
        ("?created_to=2026-11-13T12:00:00Z", ["c2", "c1"]),
        ("?created_from=2026-11-13T11:00:00&created_to=2026-11-13T13:00:00", ["c3", "c2"]),
        # 16:30 IST = 11:00 UTC
        ("?created_from=2026-11-13T16:30:00%2B05:30", ["c5", "c4", "c3", "c2"]),
        ("?agent_id=nobody", []),
    ],
)
def test_list_filters(db, query, expected):
    _seed_calls(db)
    res = _list(db, query)
    assert _ids(res) == expected
    assert res.json()["total"] == len(expected)


def test_list_filter_total_counts_whole_filtered_set(db):
    _seed_calls(db)
    res = _list(db, "?agent_id=agent-a&limit=1&offset=1")
    assert _ids(res) == ["c2"] and res.json()["total"] == 3


def test_list_rejects_reversed_dates(db):
    _seed_calls(db)
    res = _list(db, "?created_from=2026-11-14T00:00:00Z&created_to=2026-11-13T00:00:00Z")
    assert res.status_code == 422


def test_filters_never_widen_the_org():
    query = call_log_service._list_query("org-1", extra={"org_id": "org-2", "agent_id": "a"})
    assert query == {"org_id": "org-1", "agent_id": "a"}


def test_call_list_filters_normalises_dates_to_utc():
    ist = timezone(timedelta(hours=5, minutes=30))
    query = call_log_service.call_list_filters(
        agent_id=" ",
        status="completed",
        created_from=datetime(2026, 11, 13, 16, 30, tzinfo=ist),
        created_to=datetime(2026, 11, 14, 0, 0),
    )
    assert query == {
        "status": "completed",
        "created_at": {"$gte": "2026-11-13T11:00:00+00:00", "$lt": "2026-11-14T00:00:00+00:00"},
    }


# -------------------------------------------------------------- webhook ----


@pytest.mark.asyncio
async def test_webhook_payload_carries_transcript_turns(db, monkeypatch):
    monkeypatch.setattr(settings, "PROVIDER_AUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())
    db["Agents"].insert_one({"agent_id": "agent-1", "org_id": "org-1",
                             "config": {"webhook": {"enabled": True, "url": "https://h.example/x"}}})
    wh.rotate_agent_secret("org-1", "agent-1", db=db)
    db["CallLogs"].insert_many([_call_doc(), _call_doc(call_id="call-2", transcript_url=None,
                                                         call_response="no_answer")])
    for cid in ("call-1", "call-2"):
        wh.schedule_for_call(db["CallLogs"].find_one({"call_id": cid}), db=db, settle_seconds=0)

    bodies: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies[body["data"]["call_id"]] = body
        return httpx.Response(200)

    storage = _FakeStorage({("voicera-calls", "org-1/call-1/transcript.txt"): TRANSCRIPT.encode()})
    with patch.object(ts, "_new_storage", return_value=storage):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await wh.dispatch_due(client=client, db=db) == 2

    turns = bodies["call-1"]["data"]["transcript"]
    assert len(turns) == 4 and turns[0]["speaker"] == "agent"
    assert bodies["call-2"]["data"]["transcript"] is None


@pytest.mark.asyncio
async def test_webhook_still_sends_when_storage_is_down(db, monkeypatch):
    monkeypatch.setattr(settings, "PROVIDER_AUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())
    db["Agents"].insert_one({"agent_id": "agent-1", "org_id": "org-1",
                             "config": {"webhook": {"enabled": True, "url": "https://h.example/x"}}})
    wh.rotate_agent_secret("org-1", "agent-1", db=db)
    db["CallLogs"].insert_one(_call_doc())
    wh.schedule_for_call(db["CallLogs"].find_one({"call_id": "call-1"}), db=db, settle_seconds=0)
    with patch.object(ts, "_new_storage", return_value=_FakeStorage({})):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as c:
            await wh.dispatch_due(client=c, db=db)
    row = db[wh.COLLECTION].find_one({"call_id": "call-1"})
    assert row["state"] == wh.STATE_DELIVERED
