"""Raya-compatible post-call webhook and signed recording links."""

from __future__ import annotations

import json
from pathlib import Path
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
from app.services.call_output.bluedots import loki
from app.services.call_output.bluedots.signals import extract
from app.services.raya_webhook import RAYA_FIELDS, build_raya_payload, raya_transcript

SAMPLES = Path(__file__).parent / "sample_data"
RAYA_ANSWERED = json.loads((SAMPLES / "raya_webhook_answered.json").read_text())
RAYA_FAILED = json.loads((SAMPLES / "raya_webhook_failed.json").read_text())

TURNS = [
    {"index": 0, "role": "assistant", "speaker": "agent", "timestamp": "2026-11-20T14:11:36.085+00:00",
     "text": "ನಮಸ್ಕಾರ"},
    {"index": 1, "role": "user", "speaker": "caller", "timestamp": "2026-11-20T14:11:41.286+00:00",
     "text": "ಹೌದು"},
    {"index": 2, "role": "assistant", "speaker": "agent", "timestamp": "2026-11-20T14:11:45.000+00:00",
     "text": "ಜಾಬ್ ಇದೆ"},
]
NS = 1_000_000_000
T0 = int(datetime(2026, 11, 20, 14, 11, 43, tzinfo=timezone.utc).timestamp()) * NS
TOOLS = [  # as call_output stores them (asdict(ToolCall))
    {"ts_ns": T0, "trace_id": "6d72013b", "tool": "fetch_jobs", "ok": True, "error": None,
     "arguments": {"query_text": "Electrical Diploma jobs in Hubballi"},
     "result": json.dumps({"message": {"items": [{"item_id": "j-1", "item_state": {"role": "Electrician"}}]}})},
]


def _call(**extra: Any) -> dict[str, Any]:
    doc = {
        "call_id": "c-1", "org_id": "org-1", "agent_id": "agent-1", "call_type": "outbound",
        "status": "completed", "call_response": "answered",
        "from_number": "+91 80000 00000", "to_number": "919900000001",
        "custom_variables": {"contact_name": "Ravi", "location": "Hubli"},
        "campaign_id": "camp-1", "queued_run_id": "run-2",
        "start_time_utc": "2026-11-20T14:11:30+00:00", "end_time_utc": "2026-11-20T14:13:40.250000+00:00",
        "duration": 130.4, "created_at": datetime(2026, 11, 20, 14, 11, 28, tzinfo=timezone.utc),
        "call_output": {"call_answered": "Yes"}, "recording_url": "minio://voicera-calls/c-1/recording.wav",
    }
    doc.update(extra)
    return doc


def _type_name(value: Any) -> str:
    return "null" if value is None else type(value).__name__


def test_fields_match_the_real_raya_bodies():
    assert list(RAYA_ANSWERED) == list(RAYA_FIELDS) == list(RAYA_FAILED)
    answered = build_raya_payload(_call(), transcript=TURNS, recording_url="https://x/rec",
                                  system_prompt="Prompt", tool_calls=TOOLS)
    failed = build_raya_payload(_call(call_response="no_answer", duration=None), transcript=TURNS,
                                recording_url="https://x/rec", system_prompt="Prompt", tool_calls=TOOLS)
    for ours, theirs in ((answered, RAYA_ANSWERED), (failed, RAYA_FAILED)):
        assert list(ours) == list(theirs)
        types = {k: (_type_name(ours[k]), _type_name(theirs[k])) for k in theirs}
        assert {k: t for k, t in types.items() if t[0] != t[1]} == {}


def test_answered_values():
    body = build_raya_payload(_call(), transcript=TURNS, recording_url="https://x/rec",
                              system_prompt="Prompt", tool_calls=TOOLS)
    assert body["uuid"] == "c-1" and body["outcome"] == "Completed"
    assert body["caller_no"] is None  # outbound, as in Raya's body
    assert body["to_number"] == "+919900000001" and body["out_did"] == 918000000000
    assert body["in_did"] is None and body["timezone"] is None and body["enhanced_recording_url"] is None
    assert body["call_start_time"] == "2026-11-20T14:11:30.000Z"
    assert body["call_end_time"] == "2026-11-20T14:13:40.250Z"
    assert body["created_at"] == "2026-11-20T14:11:28.000Z"
    for key in ("call_start_time", "call_end_time", "created_at"):
        assert len(body[key]) == len(RAYA_ANSWERED[key])
    assert body["call_duration"] == 130
    assert body["agent_args"] == {"contact_name": "Ravi", "location": "Hubli"}
    assert body["call_output"] == {"call_answered": "Yes"} and body["call_recording_url"] == "https://x/rec"


def test_failure_values_match_raya():
    body = build_raya_payload(_call(call_response="busy", duration=7, call_output={"call_answered": "No"}),
                              transcript=TURNS, recording_url="https://x/rec")
    for key in ("call_transcript", "call_recording_url", "enhanced_recording_url", "call_output", "timezone"):
        assert body[key] is None and RAYA_FAILED[key] is None, key
    assert body["outcome"] == "Failure" and body["call_duration"] == 0 == RAYA_FAILED["call_duration"]


def test_inbound_numbers():
    body = build_raya_payload(_call(call_type="inbound", from_number="919900000001", to_number="+918000000000"),
                              transcript=[], recording_url=None)
    assert body["caller_no"] == "+919900000001" and body["to_number"] == "+918000000000"
    assert body["in_did"] == 918000000000 and body["out_did"] is None
    assert body["call_recording_url"] is None and body["call_transcript"] == []


def test_transcript_messages_have_raya_shapes():
    messages = raya_transcript(TURNS, system_prompt="Prompt", tool_calls=TOOLS)
    assert [m["role"] for m in messages] == ["system", "assistant", "user", "assistant", "tool", "assistant"]
    assert messages[0] == {"role": "system", "content": "Prompt"}
    assert messages[1] == {"role": "assistant", "content": "ನಮಸ್ಕಾರ"}
    call, result = messages[3], messages[4]
    assert call["content"] is None and call["tool_calls"][0]["function"]["name"] == "fetch_jobs"
    assert json.loads(call["tool_calls"][0]["function"]["arguments"]) == TOOLS[0]["arguments"]
    assert result["tool_call_id"] == call["tool_calls"][0]["id"] == "call_6d72013b"
    assert result["content"] == repr(json.loads(TOOLS[0]["result"]))  # Python dict string, as Raya
    # Every message and tool call uses keys Raya's own transcript uses.
    raya_keys = {tuple(sorted(m)) for m in RAYA_ANSWERED["call_transcript"]}
    assert {tuple(sorted(m)) for m in messages} <= raya_keys
    raya_call = next(m for m in RAYA_ANSWERED["call_transcript"] if m.get("tool_calls"))["tool_calls"][0]
    assert set(call["tool_calls"][0]) <= set(raya_call) and set(call["tool_calls"][0]["function"]) == set(raya_call["function"])
    assert isinstance(raya_call["function"]["arguments"], str)


def test_transcript_edge_cases():
    assert raya_transcript(None) == []
    assert raya_transcript([], system_prompt="P") == [{"role": "system", "content": "P"}]
    untimed = [{"speaker": "agent", "text": "a"}, {"speaker": "caller", "text": "b"}]
    assert [m["content"] for m in raya_transcript(untimed)] == ["a", "b"]
    cut = dict(TOOLS[0], result='{"message": {"items": [{"item_id": "j-1"', ok=True)
    assert raya_transcript([], tool_calls=[cut])[1]["content"] == cut["result"]  # truncated: as logged
    failed = dict(TOOLS[0], ok=False, result=None, error="http_error: 404", arguments=None)
    msgs = raya_transcript([], tool_calls=[failed])
    assert msgs[0]["tool_calls"][0]["function"]["arguments"] == "{}" and msgs[1]["content"] == "http_error: 404"


def _gateway(ts: int, trace: str, tool: str, status: str, message: str, level: str = "DEBUG", **attrs: Any):
    record = {"body": message, "traceid": trace, "attributes": {
        "operation": "RestApiAdapter.execute", "session_id": "919900000001:c-1", "tool_name": tool,
        "status": status, **attrs}}
    return loki.parse_line(ts, {"job": "action_gateway", "level": level}, json.dumps(record))


def test_signals_keep_tool_arguments_and_results_from_debug_lines():
    """Line shapes as AI DPG logs them on the box at DEBUG."""
    profile = '{"user_id":null,"items":[]}'
    lines = [
        _gateway(1, "tp", "fetch_profile", "pending", "rest_api_request tool=fetch_profile method=GET",
                 method="GET", params={},
                 url="https://signals.example/api/v1/admin/participant?phone_number=919900000001"),
        _gateway(2, "tp", "fetch_profile", "received", "rest_api_response tool=fetch_profile status=200",
                 body=profile, status_code=200),
        _gateway(3, "tp", "fetch_profile", "success", "rest_api_session_values tool=fetch_profile", level="INFO"),
        _gateway(4, "tp", "fetch_profile", "success", "rest_api_execute", level="INFO", latency_ms=333),
        _gateway(5, "tj", "fetch_jobs", "pending", "rest_api_request tool=fetch_jobs method=POST",
                 method="POST", params={"query_text": "Electrical jobs"}, url="https://signals.example/search"),
        _gateway(6, "tj", "fetch_jobs", "success", "rest_api_execute", level="INFO"),
        _gateway(7, "ta", "apply_job", "failure", "rest_api_http_error tool=apply_job status=404", level="WARN",
                 error="http_error: 404"),
    ]
    tools = extract(lines).tools
    assert [(t.tool, t.ok) for t in tools] == [("fetch_profile", True), ("fetch_jobs", True), ("apply_job", False)]
    assert tools[0].arguments == {"phone_number": "919900000001"} and tools[0].result == profile
    assert tools[1].arguments == {"query_text": "Electrical jobs"} and tools[1].result is None
    assert tools[2].arguments is None and tools[2].error == "http_error: 404"


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
        "prompts": {"system_prompt": "Prompt"},
        "webhook": {"enabled": True, "url": "https://hooks.example/raya", "format": "raya"}}})
    secret = wh.rotate_agent_secret("org-1", "agent-1", db=db)
    db["CallLogs"].insert_one(_call(queued_run_id=None, call_output_signals={"tools": TOOLS}))
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
    assert list(body) == list(RAYA_FIELDS) and body["uuid"] == "c-1" and body["outcome"] == "Completed"
    assert [m["role"] for m in body["call_transcript"]][:2] == ["system", "assistant"]
    assert any(m.get("tool_calls") for m in body["call_transcript"])
    assert body["call_recording_url"].startswith("https://bluedots.example/api/")
    assert "event" not in body and "data" not in body
    ts = int(seen["headers"]["X-VoicEra-Timestamp"])
    assert wh.verify_signature(secret, ts, seen["body"], seen["headers"]["X-VoicEra-Signature"],
                               now=datetime.fromtimestamp(ts, timezone.utc))
