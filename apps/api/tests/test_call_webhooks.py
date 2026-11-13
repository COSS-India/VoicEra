"""Post-call webhook: scheduling, signing, delivery, retries and routes."""

from __future__ import annotations

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
from app.models.schemas import AgentConfigPayload, AgentWebhook
from app.routers import agents as agents_router
from app.routers import calls as calls_router
from app.services import call_log_service
from app.services import call_webhook_service as svc

URL = "https://hooks.bluedots.example/voicera"


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    monkeypatch.setattr(settings, "PROVIDER_AUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture(autouse=True)
def _no_storage(monkeypatch):
    # Transcript loading reads MinIO; these tests cover delivery, not storage.
    monkeypatch.setattr(svc, "_load_transcript_turns", lambda call: None)


@pytest.fixture()
def db():
    return mongomock.MongoClient()["voicera_test"]


def _agent(db, *, enabled=True, url=URL, with_secret=True, agent_id="agent-1", org_id="org-1"):
    db["Agents"].insert_one(
        {
            "agent_id": agent_id,
            "org_id": org_id,
            "name": "KKB",
            "config": {"webhook": {"enabled": enabled, "url": url}},
        }
    )
    if with_secret:
        return svc.rotate_agent_secret(org_id, agent_id, db=db)
    return None


def _call(db, *, status="completed", call_id="call-1", **extra):
    doc = {
        "call_id": call_id,
        "org_id": "org-1",
        "agent_id": "agent-1",
        "call_type": "outbound",
        "status": status,
        "call_response": "answered" if status == "completed" else "failed",
        "from_number": "+918000000000",
        "to_number": "+919999999999",
        "custom_variables": {"participant_id": "P-42", "location": "Hubli"},
        "campaign_id": "camp-1",
        "transcript_url": "minio://voicera-calls/org-1/call-1/transcript.txt",
        "start_time_utc": "2026-11-13T10:00:00+00:00",
        "end_time_utc": "2026-11-13T10:03:00+00:00",
        "duration": 180.0,
    }
    doc.update(extra)
    db["CallLogs"].insert_one(doc)
    return db["CallLogs"].find_one({"call_id": call_id})


def _row(db, call_id="call-1"):
    return db[svc.COLLECTION].find_one({"call_id": call_id})


def _make_due(db, call_id="call-1"):
    db[svc.COLLECTION].update_one(
        {"call_id": call_id},
        {"$set": {"next_attempt_at": datetime.now(timezone.utc) - timedelta(seconds=1)}},
    )


# ---------------------------------------------------------------- schema ----


def test_webhook_schema_requires_https_and_url_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "CALL_WEBHOOK_ALLOW_HTTP", False)
    assert AgentWebhook(enabled=True, url=URL).url == URL
    assert AgentWebhook().enabled is False
    assert AgentWebhook(url="  ").url is None
    with pytest.raises(ValueError):
        AgentWebhook(enabled=True, url="http://insecure.example/hook")
    with pytest.raises(ValueError):
        AgentWebhook(enabled=True, url="not-a-url")
    with pytest.raises(ValueError):
        AgentWebhook(enabled=True)


def test_webhook_schema_allows_http_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "CALL_WEBHOOK_ALLOW_HTTP", True)
    assert AgentWebhook(enabled=True, url="http://localhost:9000/h").url == "http://localhost:9000/h"


def _config(**extra) -> dict[str, Any]:
    stack = {
        "stt_config": {"provider": "deepgram", "model": "nova-3", "language": "hi"},
        "tts_config": {"provider": "cartesia", "model": "sonic", "language": "hi"},
        "llm_config": {"provider": "bluedots", "model": "bluedots"},
    }
    base = {
        "prompts": {"system_prompt": "x", "greeting_message": "hi"},
        "language": {"primary": "hi", "secondary": []},
        "models": {"hi": stack},
    }
    base.update(extra)
    return base


def test_merge_keeps_existing_webhook_when_incoming_config_omits_it():
    from app.services import agent_service

    existing = AgentConfigPayload.model_validate(
        _config(webhook={"enabled": True, "url": URL})
    ).model_dump(mode="python")
    incoming = AgentConfigPayload.model_validate(_config())
    with patch.object(agent_service, "validate_agent_config", side_effect=lambda c, org_id: c):
        merged = agent_service._merge_config(existing, incoming, org_id="org-1")
    assert merged.webhook.enabled is True and merged.webhook.url == URL

    incoming_off = AgentConfigPayload.model_validate(_config(webhook={"enabled": False}))
    with patch.object(agent_service, "validate_agent_config", side_effect=lambda c, org_id: c):
        merged = agent_service._merge_config(existing, incoming_off, org_id="org-1")
    assert merged.webhook.enabled is False


# ------------------------------------------------------------ scheduling ----


def test_schedule_creates_one_row_per_terminal_call(db):
    _agent(db)
    call = _call(db)
    before = datetime.now(timezone.utc)
    assert svc.schedule_for_call(call, db=db) is True
    assert svc.schedule_for_call(call, db=db) is True
    assert db[svc.COLLECTION].count_documents({}) == 1
    row = _row(db)
    assert row["state"] == svc.STATE_PENDING and row["attempts"] == 0 and row["url"] == URL
    due = row["next_attempt_at"].replace(tzinfo=timezone.utc)
    assert due >= before + timedelta(seconds=settings.CALL_WEBHOOK_SETTLE_SECONDS - 1)


@pytest.mark.parametrize("status", ["initiated", "ringing", "in_progress"])
def test_schedule_skips_non_terminal_calls(db, status):
    _agent(db)
    assert svc.schedule_for_call(_call(db, status=status), db=db) is False
    assert db[svc.COLLECTION].count_documents({}) == 0


def test_schedule_skips_disabled_or_missing_agent(db):
    _agent(db, enabled=False, url=None)
    assert svc.schedule_for_call(_call(db), db=db) is False
    assert svc.schedule_for_call(_call(db, call_id="c2", agent_id="nobody"), db=db) is False
    assert db[svc.COLLECTION].count_documents({}) == 0


def test_schedule_never_raises():
    class Broken:
        def __getitem__(self, name):
            raise RuntimeError("db down")

    assert svc.schedule_for_call({"call_id": "x", "org_id": "o", "agent_id": "a",
                                  "status": "completed"}, db=Broken()) is False


def test_call_log_patch_to_completed_schedules_webhook(db):
    _agent(db)
    _call(db, status="ringing")
    with patch.object(call_log_service, "get_database", return_value=db):
        call_log_service.patch_call_log("org-1", "call-1", {"call_response": "busy"})
        assert db[svc.COLLECTION].count_documents({}) == 0
        call_log_service.patch_call_log(
            "org-1", "call-1",
            {"status": "completed", "end_time_utc": "2026-11-13T10:03:00+00:00"},
        )
    assert _row(db)["state"] == svc.STATE_PENDING


def test_failed_dial_via_update_call_log_schedules_webhook(db):
    _agent(db)
    _call(db, status="initiated")
    with patch.object(call_log_service, "get_database", return_value=db):
        call_log_service.update_call_log("call-1", {"status": "failed", "call_response": "failed"})
    assert _row(db) is not None


# ------------------------------------------------------------- signature ----


def test_sign_and_verify_round_trip():
    body = b'{"a":1}'
    now = datetime.now(timezone.utc)
    ts = int(now.timestamp())
    sig = svc.sign("whsec_x", ts, body)
    assert sig.startswith("v1=")
    assert svc.verify_signature("whsec_x", ts, body, sig, now=now)
    assert not svc.verify_signature("whsec_y", ts, body, sig, now=now)
    assert not svc.verify_signature("whsec_x", ts, b'{"a":2}', sig, now=now)
    assert not svc.verify_signature("whsec_x", ts, body, sig, now=now + timedelta(minutes=10))
    assert not svc.verify_signature("whsec_x", "nan", body, sig, now=now)


def test_secret_is_encrypted_at_rest(db):
    secret = _agent(db)
    stored = db["Agents"].find_one({"agent_id": "agent-1"})["webhook_secret"]
    assert secret.startswith("whsec_") and secret not in str(stored)
    assert svc.agent_secret(db["Agents"].find_one({"agent_id": "agent-1"})) == secret
    assert svc.rotate_agent_secret("org-1", "agent-1", db=db) != secret
    with pytest.raises(svc.AgentWebhookNotFoundError):
        svc.rotate_agent_secret("org-1", "missing", db=db)


# -------------------------------------------------------------- delivery ----


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_deliver_success_sends_signed_payload(db):
    secret = _agent(db)
    svc.schedule_for_call(_call(db), db=db)
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["body"] = request.content
        return httpx.Response(204)

    async with _client(handler) as client:
        row = await svc.deliver(_row(db), client=client, db=db)

    assert row["state"] == svc.STATE_DELIVERED and row["attempts"] == 1
    headers, body = seen["headers"], seen["body"]
    assert headers["x-voicera-event"] == "call.ended"
    assert headers["x-voicera-delivery"] == "call-1"
    assert svc.verify_signature(secret, headers["x-voicera-timestamp"], body,
                                headers["x-voicera-signature"])
    payload = json.loads(body)
    assert payload["event"] == "call.ended" and payload["attempt"] == 1
    data = payload["data"]
    assert data["custom_variables"]["participant_id"] == "P-42"
    assert data["call_response"] == "answered" and data["campaign_id"] == "camp-1"
    assert data["artifacts"]["transcript_path"] == f"{settings.API_V1_PREFIX}/calls/call-1/transcript"
    assert data["artifacts"]["recording_path"] is None
    assert "transcript_url" not in data  # internal storage URL never leaves VoicEra


@pytest.mark.asyncio
async def test_deliver_retries_with_backoff_then_fails(db, monkeypatch):
    monkeypatch.setattr(settings, "CALL_WEBHOOK_MAX_ATTEMPTS", 3)
    _agent(db)
    svc.schedule_for_call(_call(db), db=db)

    async with _client(lambda r: httpx.Response(503)) as client:
        start = datetime.now(timezone.utc)
        row = await svc.deliver(_row(db), client=client, db=db)
        assert row["state"] == svc.STATE_PENDING and row["attempts"] == 1
        assert row["last_status_code"] == 503 and row["last_error"] == "HTTP 503"
        wait = row["next_attempt_at"].replace(tzinfo=timezone.utc) - start
        assert timedelta(seconds=29) <= wait <= timedelta(seconds=32)

        row = await svc.deliver(_row(db), client=client, db=db)
        assert row["attempts"] == 2 and row["state"] == svc.STATE_PENDING
        row = await svc.deliver(_row(db), client=client, db=db)
        assert row["attempts"] == 3 and row["state"] == svc.STATE_FAILED
        assert row["next_attempt_at"] is None


@pytest.mark.asyncio
async def test_deliver_network_error_is_retried(db):
    _agent(db)
    svc.schedule_for_call(_call(db), db=db)

    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    async with _client(boom) as client:
        row = await svc.deliver(_row(db), client=client, db=db)
    assert row["state"] == svc.STATE_PENDING and "ConnectError" in row["last_error"]


@pytest.mark.asyncio
async def test_deliver_without_secret_retries_and_disabled_agent_stops(db):
    _agent(db, with_secret=False)
    svc.schedule_for_call(_call(db), db=db)
    async with _client(lambda r: httpx.Response(200)) as client:
        row = await svc.deliver(_row(db), client=client, db=db)
        assert row["state"] == svc.STATE_PENDING and "secret" in row["last_error"]

        db["Agents"].update_one({"agent_id": "agent-1"}, {"$set": {"config.webhook.enabled": False}})
        row = await svc.deliver(_row(db), client=client, db=db)
    assert row["state"] == svc.STATE_FAILED and "disabled" in row["last_error"]


def test_backoff_grows_and_is_capped(monkeypatch):
    monkeypatch.setattr(settings, "CALL_WEBHOOK_BACKOFF_BASE_SECONDS", 30)
    monkeypatch.setattr(settings, "CALL_WEBHOOK_BACKOFF_MAX_SECONDS", 3600)
    assert [svc.backoff_seconds(n) for n in (1, 2, 3, 8, 20)] == [30, 60, 120, 3600, 3600]


# ------------------------------------------------------- claim / dispatch ----


def test_claim_due_leases_once_and_reclaims_stale_leases(db):
    _agent(db)
    svc.schedule_for_call(_call(db), db=db)
    svc.schedule_for_call(_call(db, call_id="call-2"), db=db)
    assert svc.claim_due(limit=10, db=db) == []  # still settling

    _make_due(db)
    claimed = svc.claim_due(limit=10, db=db)
    assert [d["call_id"] for d in claimed] == ["call-1"]
    assert svc.claim_due(limit=10, db=db) == []  # leased

    later = datetime.now(timezone.utc) + timedelta(seconds=settings.CALL_WEBHOOK_LEASE_SECONDS + 1)
    reclaimed = svc.claim_due(limit=10, db=db, now=later)
    assert {d["call_id"] for d in reclaimed} == {"call-1", "call-2"}


@pytest.mark.asyncio
async def test_dispatch_due_delivers_everything_due(db):
    _agent(db)
    for cid in ("a", "b", "c"):
        svc.schedule_for_call(_call(db, call_id=cid), db=db)
        _make_due(db, cid)
    hits: list[str] = []

    def handler(request):
        hits.append(request.headers["x-voicera-delivery"])
        return httpx.Response(200)

    async with _client(handler) as client:
        assert await svc.dispatch_due(client=client, db=db) == 3
        assert await svc.dispatch_due(client=client, db=db) == 0
    assert sorted(hits) == ["a", "b", "c"]
    assert db[svc.COLLECTION].count_documents({"state": svc.STATE_DELIVERED}) == 3


def test_redeliver_resets_or_schedules(db):
    _agent(db)
    svc.schedule_for_call(_call(db), db=db)
    db[svc.COLLECTION].update_one({"call_id": "call-1"},
                                  {"$set": {"state": svc.STATE_FAILED, "attempts": 8}})
    row = svc.redeliver("org-1", "call-1", db=db)
    assert row["state"] == svc.STATE_PENDING and row["attempts"] == 0

    _call(db, call_id="call-9")  # ended but never scheduled
    assert svc.redeliver("org-1", "call-9", db=db)["state"] == svc.STATE_PENDING
    _call(db, call_id="call-live", status="in_progress")
    assert svc.redeliver("org-1", "call-live", db=db) is None
    assert svc.redeliver("org-2", "call-1", db=db) is None  # other org


# ---------------------------------------------------------------- routes ----


def _app(db, role="admin", org_id="org-1") -> TestClient:
    app = FastAPI()
    app.include_router(agents_router.router, prefix="/api/v1")
    app.include_router(calls_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {
        "email": "a@example.com", "org_id": org_id, "role": role,
    }
    return TestClient(app)


def test_rotate_secret_route_is_admin_only(db):
    _agent(db, with_secret=False)
    with patch.object(svc, "get_database", return_value=db):
        res = _app(db, role="member").post("/api/v1/agents/agent-1/webhook/secret")
        assert res.status_code == 403
        res = _app(db).post("/api/v1/agents/agent-1/webhook/secret")
        assert res.status_code == 201 and res.json()["secret"].startswith("whsec_")
        assert _app(db).post("/api/v1/agents/nope/webhook/secret").status_code == 404


def test_webhook_status_and_redeliver_routes(db):
    _agent(db)
    _call(db)
    _call(db, call_id="live", status="in_progress")
    with patch.object(svc, "get_database", return_value=db):
        client = _app(db)
        assert client.get("/api/v1/calls/call-1/webhook").status_code == 404
        res = client.post("/api/v1/calls/call-1/webhook/redeliver")
        assert res.status_code == 202 and res.json()["state"] == "pending"
        body = client.get("/api/v1/calls/call-1/webhook").json()
        assert body["call_id"] == "call-1" and body["url"] == URL
        assert isinstance(body["next_attempt_at"], str)
        assert client.post("/api/v1/calls/live/webhook/redeliver").status_code == 409
        assert _app(db, org_id="org-2").get("/api/v1/calls/call-1/webhook").status_code == 404
