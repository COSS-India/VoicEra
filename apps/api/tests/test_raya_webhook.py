"""Raya-compatible post-call webhook and signed recording links."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
import mongomock
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.models.schemas import AgentWebhook
from app.routers import calls as calls_router
from app.services import call_log_service
from app.services import call_webhook_service as wh
from app.services import recording_links
from app.services.raya_webhook import build_raya_payload, contact_id_for, raya_transcript

RAYA_FIELDS = [
    "uuid", "caller_no", "to_number", "in_did", "out_did", "call_transcript",
    "call_recording_url", "outcome", "call_start_time", "call_end_time", "call_duration",
    "agent_id", "agent_args", "timezone", "call_output", "created_at", "batch_id", "contact_id",
]
TURNS = [
    {"index": 0, "role": "assistant", "speaker": "agent", "timestamp": "2026-11-20T14:11:36.085+00:00",
     "text": "ನಮಸ್ಕಾರ"},
    {"index": 1, "role": "user", "speaker": "caller", "timestamp": "2026-11-20T14:11:41.286+00:00",
     "text": "ಹೌದು"},
]


def _call(**extra: Any) -> dict[str, Any]:
    doc = {
        "call_id": "c-1", "org_id": "org-1", "agent_id": "agent-1", "call_type": "outbound",
        "status": "completed", "call_response": "answered",
        "from_number": "+91 80000 00000", "to_number": "+919900000001",
        "custom_variables": {"contact_name": "Ravi", "location": "Hubli"},
        "campaign_id": "camp-1", "queued_run_id": "run-2",
        "start_time_utc": "2026-11-20T14:11:30+00:00", "end_time_utc": "2026-11-20T14:13:40.250000+00:00",
        "duration": 130.4, "created_at": datetime(2026, 11, 20, 14, 11, 28, tzinfo=timezone.utc),
        "call_output": {"call_answered": "Yes"}, "recording_url": "minio://voicera-calls/c-1/recording.wav",
    }
    doc.update(extra)
    return doc


def test_raya_payload_fields_and_values():
    body = build_raya_payload(_call(), transcript=TURNS, recording_url="https://x/rec", contact_id="run-1")
    assert list(body) == RAYA_FIELDS
    assert body["uuid"] == "c-1" and body["outcome"] == "Completed"
    assert body["caller_no"] == "918000000000" and body["to_number"] == "919900000001"
    assert body["out_did"] == 918000000000 and body["in_did"] is None
    assert body["call_start_time"] == "2026-11-20T14:11:30Z"
    assert body["call_end_time"] == "2026-11-20T14:13:40.250Z"
    assert body["created_at"] == "2026-11-20T14:11:28Z"
    assert body["call_duration"] == 130 and isinstance(body["call_duration"], int)
    assert body["agent_args"] == {"contact_name": "Ravi", "location": "Hubli"}
    assert body["timezone"] == "UTC" and body["batch_id"] == "camp-1" and body["contact_id"] == "run-1"
    assert body["call_output"] == {"call_answered": "Yes"} and body["call_recording_url"] == "https://x/rec"
    assert body["call_transcript"] == [
        {"role": "assistant", "content": "ನಮಸ್ಕಾರ", "timestamp": "2026-11-20T14:11:36.085+00:00"},
        {"role": "user", "content": "ಹೌದು", "timestamp": "2026-11-20T14:11:41.286+00:00"},
    ]


def test_raya_payload_inbound_and_failure():
    inbound = build_raya_payload(_call(call_type="inbound", from_number="+919900000001",
                                       to_number="+918000000000"),
                                 transcript=TURNS, recording_url=None, contact_id=None)
    assert inbound["in_did"] == 918000000000 and inbound["out_did"] is None
    assert inbound["caller_no"] == "919900000001" and inbound["call_recording_url"] == ""
    failed = build_raya_payload(_call(call_response="no_answer", duration=None, end_time_utc=None),
                                transcript=TURNS, recording_url="https://x/rec", contact_id=None)
    assert failed["outcome"] == "Failure" and failed["call_transcript"] == []
    assert failed["call_recording_url"] == "" and failed["call_output"] == {}
    assert failed["call_duration"] is None and failed["call_end_time"] is None
    assert raya_transcript(None) == []


def test_contact_id_is_the_root_of_the_retry_chain():
    db = mongomock.MongoClient()["t"]
    db["QueuedRuns"].insert_many([
        {"queued_run_id": "run-1", "parent_queued_run_id": None},
        {"queued_run_id": "run-2", "parent_queued_run_id": "run-1"},
        {"queued_run_id": "run-3", "parent_queued_run_id": "run-2"},
    ])
    assert contact_id_for(_call(queued_run_id="run-3"), db) == "run-1"
    assert contact_id_for(_call(queued_run_id="run-1"), db) == "run-1"
    assert contact_id_for(_call(queued_run_id=None), db) is None


@pytest.fixture()
def links(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://bluedots.example")
    monkeypatch.setattr(settings, "RECORDING_LINK_TTL_SECONDS", 3600)


def test_signed_recording_url_verifies_and_expires(links, monkeypatch):
    url = recording_links.signed_recording_url("org-1", "c-1", now=1_000_000)
    parsed = urlparse(url)
    assert parsed.scheme == "https" and parsed.netloc == "bluedots.example"
    assert parsed.path == f"{settings.API_V1_PREFIX}/calls/c-1/recording/signed"
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert q["org"] == "org-1" and int(q["expires"]) == 1_003_600
    assert recording_links.verify("org-1", "c-1", 1_003_600, q["sig"], now=1_003_000)
    assert not recording_links.verify("org-1", "c-1", 1_003_600, q["sig"], now=1_003_601)
    assert not recording_links.verify("org-1", "c-2", 1_003_600, q["sig"], now=1_003_000)
    assert not recording_links.verify("org-2", "c-1", 1_003_600, q["sig"], now=1_003_000)
    assert not recording_links.verify("org-1", "c-1", 1_009_999, q["sig"], now=1_003_000)
    monkeypatch.setattr(settings, "SECRET_KEY", "rotated")
    assert not recording_links.verify("org-1", "c-1", 1_003_600, q["sig"], now=1_003_000)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://front.example/")
    assert recording_links.signed_recording_url("org-1", "c-1").startswith("https://front.example/api/")


def test_signed_recording_route(links):
    db = mongomock.MongoClient()["t"]
    db["CallLogs"].insert_one(_call())
    app = FastAPI()
    app.include_router(calls_router.router, prefix=settings.API_V1_PREFIX)
    client = TestClient(app)
    url = urlparse(recording_links.signed_recording_url("org-1", "c-1"))
    with patch.object(call_log_service, "get_database", return_value=db), \
         patch.object(calls_router, "_recording_response",
                      return_value=calls_router.StreamingResponse(iter([b"RIFF"]), media_type="audio/wav")):
        ok = client.get(f"{url.path}?{url.query}")
        assert ok.status_code == 200 and ok.content == b"RIFF"
        tampered = client.get(f"{url.path}?{url.query}".replace("org=org-1", "org=org-2"))
        assert tampered.status_code == 403
        assert client.get(f"{settings.API_V1_PREFIX}/calls/c-1/recording/signed?org=org-1&expires=1&sig=x").status_code == 403
        # The logged-in route still needs a login.
        assert client.get(f"{settings.API_V1_PREFIX}/calls/c-1/recording").status_code in (401, 403)


def test_webhook_format_setting():
    assert AgentWebhook().format == "voicera"
    assert AgentWebhook(enabled=True, url="https://h.example/x", format="raya").format == "raya"
    with pytest.raises(ValueError):
        AgentWebhook(format="other")
    assert wh.webhook_format({"config": {"webhook": {"format": "raya"}}}) == "raya"
    assert wh.webhook_format({"config": {"webhook": {}}}) == "voicera"
    assert wh.webhook_format(None) == "voicera"


@pytest.mark.asyncio
async def test_raya_agent_receives_the_raya_body_signed(links, monkeypatch):
    monkeypatch.setattr(settings, "PROVIDER_AUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())
    db = mongomock.MongoClient()["t"]
    db["Agents"].insert_one({"agent_id": "agent-1", "org_id": "org-1", "config": {
        "webhook": {"enabled": True, "url": "https://hooks.example/raya", "format": "raya"}}})
    secret = wh.rotate_agent_secret("org-1", "agent-1", db=db)
    db["CallLogs"].insert_one(_call(queued_run_id=None))
    wh.schedule_for_call(db["CallLogs"].find_one({}), db=db, settle_seconds=0)
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"], seen["headers"] = request.content, request.headers
        return httpx.Response(200)

    monkeypatch.setattr(wh, "_load_transcript_turns", lambda call: TURNS)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        row = await wh.deliver(db[wh.COLLECTION].find_one({}), client=client, db=db)
    assert row["state"] == "delivered"
    body = json.loads(seen["body"])
    assert list(body) == RAYA_FIELDS and body["uuid"] == "c-1" and body["outcome"] == "Completed"
    assert body["call_recording_url"].startswith("https://bluedots.example/api/")
    assert "event" not in body and "data" not in body
    ts = int(seen["headers"]["X-VoicEra-Timestamp"])
    assert wh.verify_signature(secret, ts, seen["body"], seen["headers"]["X-VoicEra-Signature"],
                               now=datetime.fromtimestamp(ts, timezone.utc))
