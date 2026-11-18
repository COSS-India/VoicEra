"""Post-call call_output: Blue Dots adapter (Loki signals -> funnel) and the core."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
from app.models.schemas import AgentCallOutput, AgentConfigPayload
from app.routers import calls as calls_router
from app.services import call_log_service
from app.services import call_webhook_service as wh
from app.services.call_output import service as svc
from app.services.call_output.base import CallOutputNotReady, CallOutputResult
from app.services.call_output.bluedots import funnel, llm, loki, provider as bd_provider
from app.services.call_output.bluedots.signals import CallSignals, ToolCall, Turn, extract

FIXTURE = Path(__file__).parent / "sample_data" / "bluedots_sample_call_loki.jsonl"
SAMPLE_CALL_ID = "vb-T21-0-0-168782"
SAMPLE_SESSION = f"919900000001:{SAMPLE_CALL_ID}"
LOKI = "http://loki.test:3100"
LLM_URL = "https://llm.test/v1"


def _fixture_rows() -> list[dict[str, Any]]:
    return [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]


def _fixture_lines() -> list[loki.LogLine]:
    rows = _fixture_rows()
    return [loki.parse_line(r["ts_ns"], r["stream"], r["line"]) for r in rows]


def _loki_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [{"stream": r["stream"], "values": [[str(r["ts_ns"]), r["line"]]]} for r in rows],
        },
    }


def _signals(phases: list[str], tools: list[tuple[str, bool]]) -> CallSignals:
    return CallSignals(
        turns=[Turn(ts_ns=i, trace_id=None, phase=p, intent=None, tool_used=None) for i, p in enumerate(phases)],
        tools=[ToolCall(ts_ns=i, trace_id=None, tool=t, ok=ok) for i, (t, ok) in enumerate(tools)],
    )


def _tool_line(session: str, tool: str, ok: bool, ts: int) -> dict[str, Any]:
    attrs = {"operation": "RestApiAdapter.execute", "session_id": session, "tool_name": tool,
             "status": "success" if ok else "failure"}
    return {"ts_ns": ts, "stream": {"job": "action_gateway", "level": "INFO"},
            "line": json.dumps({"body": "rest_api_execute", "traceid": "t", "attributes": attrs})}


def _turn_line(session: str, phase: str, ts: int) -> dict[str, Any]:
    attrs = {"session_id": session, "next_subagent_id": phase, "intent": "any_input", "tool_used": False}
    return {"ts_ns": ts, "stream": {"job": "agent_core", "level": "INFO"},
            "line": json.dumps({"body": "orchestrator.stream_turn_complete", "traceid": "t", "attributes": attrs})}


# ------------------------------------------------------------ signals ----


def test_sample_call_signals_use_structured_lines_only():
    signals = extract(_fixture_lines())
    assert signals.phases == [
        "profile_resolve", "job_match", "job_match", "job_details",
        "consent", "profile_setup", "profile_setup", "apply_confirm",
    ]
    assert [(t.tool, t.ok) for t in signals.tools] == [
        ("fetch_profile", True), ("fetch_jobs", True), ("fetch_jobs", True),
        ("save_profile", False), ("save_profile", True), ("apply_job", True),
    ]
    assert signals.tools[3].error == "http_error: 400"
    assert signals.last_phase == "apply_confirm"


def test_sample_call_funnel():
    output, sources = funnel.build(extract(_fixture_lines()))
    assert output == {
        "schema": funnel.SCHEMA,
        "answered": True,
        "consent": True,
        "jobs_heard": True,
        "applied": True,
        "applications": 1,
        "last_phase": "apply_confirm",
        "drop_reason": None,
    }
    assert sources["applied"] == "apply_job succeeded"
    assert not funnel.needs_drop_judgement(extract(_fixture_lines()))


def test_funnel_jobs_fetched_but_not_read_out_needs_the_transcript():
    s = _signals(["profile_resolve", "job_match"], [("fetch_profile", True), ("fetch_jobs", True)])
    assert funnel.needs_jobs_judgement(s) and funnel.needs_drop_judgement(s)
    out, src = funnel.build(s)
    assert out["jobs_heard"] is None and out["drop_reason"] is None
    out, src = funnel.build(s, funnel.Judgement(jobs_read_out=False, drop_reason="no_suitable_jobs"))
    assert out["jobs_heard"] is False and out["drop_reason"] == "no_suitable_jobs"
    assert src["jobs_heard"] == "transcript (llm)"


def test_funnel_consent_declined_and_no_search():
    s = _signals(["profile_resolve", "consent", "consent_reask", "consent_declined"], [])
    out, _ = funnel.build(s)
    assert out["consent"] is False and out["jobs_heard"] is False and out["applied"] is False
    out, _ = funnel.build(_signals(["profile_resolve"], [("save_profile", True)]))
    assert out["consent"] is True and out["applied"] is False


# ---------------------------------------------------------------- llm ----


def test_parse_judgement_is_defensive():
    j = llm.parse_judgement('```json\n{"jobs_read_out": true, "drop_reason": "Not_Interested"}\n```',
                            model="m", ask_jobs=True, ask_drop=True)
    assert j.jobs_read_out is True and j.drop_reason == "not_interested"
    j = llm.parse_judgement('{"drop_reason": "made up"}', model="m", ask_jobs=False, ask_drop=True)
    assert j.drop_reason == "other" and j.jobs_read_out is None
    j = llm.parse_judgement("no json here", model="m", ask_jobs=True, ask_drop=True)
    assert j.jobs_read_out is None and j.drop_reason is None


@pytest.mark.asyncio
async def test_transcript_judge_request():
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"jobs_read_out": false, "drop_reason": "already_employed"}'}}]})

    judge = llm.TranscriptJudge(base_url=LLM_URL, model="gpt-4.1-mini", api_key="k", timeout=5, json_mode=True)
    turns = [{"speaker": "agent", "text": "नमस्ते"}, {"speaker": "caller", "text": "मेरे पास नौकरी है"}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        j = await judge.judge(client, turns, facts={"phases": []}, ask_jobs=True, ask_drop=True)
    assert seen["url"] == f"{LLM_URL}/chat/completions" and seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "gpt-4.1-mini" and seen["body"]["temperature"] == 0
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert "CALLER: मेरे पास नौकरी है" in seen["body"]["messages"][1]["content"]
    assert j.jobs_read_out is False and j.drop_reason == "already_employed" and j.model == "gpt-4.1-mini"


# --------------------------------------------------------------- loki ----


@pytest.mark.asyncio
async def test_fetch_call_lines_queries_by_call_id_and_filters_session():
    rows = _fixture_rows() + [_tool_line(f"919900000002:other-{SAMPLE_CALL_ID}x", "apply_job", True, 1)]
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_loki_payload(list(reversed(rows))))

    start = datetime(2026, 11, 17, 13, 0, tzinfo=timezone.utc)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        lines = await loki.fetch_call_lines(client, base_url=LOKI + "/", selector='{job="x"}',
                                            call_id=SAMPLE_CALL_ID, start=start,
                                            end=start + timedelta(minutes=5), timeout=5)
    assert seen["path"] == "/loki/api/v1/query_range"
    assert seen["params"]["query"] == '{job="x"} |= "vb-T21-0-0-168782"'
    assert seen["params"]["start"] == str(int(start.timestamp() * 1e9))
    assert seen["params"]["direction"] == "forward"
    assert all(loki.belongs_to_call(line, SAMPLE_CALL_ID) for line in lines)
    assert [l.ts_ns for l in lines] == sorted(l.ts_ns for l in lines)
    assert extract(lines).phases[-1] == "apply_confirm"


# ----------------------------------------------------------- provider ----


def _call(**extra) -> dict[str, Any]:
    doc = {
        "call_id": SAMPLE_CALL_ID, "org_id": "org-1", "agent_id": "agent-1",
        "call_type": "outbound", "status": "completed", "call_response": "answered",
        "to_number": "+919900000001", "from_number": "+918000000000",
        "start_time_utc": "2026-11-17T13:02:53+00:00", "end_time_utc": "2026-11-17T13:04:02+00:00",
        "created_at": "2026-11-17T13:02:50+00:00",
    }
    doc.update(extra)
    return doc


@pytest.fixture()
def bd_settings(monkeypatch):
    monkeypatch.setattr(settings, "BLUEDOTS_LOKI_URL", LOKI)
    monkeypatch.setattr(settings, "CALL_OUTPUT_LLM_BASE_URL", "")
    monkeypatch.setattr(settings, "CALL_OUTPUT_LLM_MODEL", "")
    monkeypatch.setattr(bd_provider, "_load_transcript", lambda call: [])


def _client_for(rows: list[dict[str, Any]], llm_reply: str | None = None, llm_status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "loki.test":
            return httpx.Response(200, json=_loki_payload(rows))
        if llm_reply is None:
            raise AssertionError("unexpected LLM call")
        return httpx.Response(llm_status, json={"choices": [{"message": {"content": llm_reply}}]})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_provider_computes_the_sample_call(bd_settings):
    async with _client_for(_fixture_rows()) as client:
        result = await bd_provider.BlueDotsCallOutputProvider().compute(
            _call(), {}, client=client, now=datetime(2026, 11, 17, 13, 5, tzinfo=timezone.utc))
    assert result.output["applied"] is True and result.output["consent"] is True
    assert result.signals["phases"][-1] == "apply_confirm"
    assert result.signals["sources"]["consent"] == "a consent-gated write succeeded"
    assert result.signals["llm_model"] is None


@pytest.mark.asyncio
async def test_provider_waits_for_logs_then_accepts_none(bd_settings):
    end = datetime(2026, 11, 17, 13, 4, 2, tzinfo=timezone.utc)
    async with _client_for([]) as client:
        with pytest.raises(CallOutputNotReady):
            await bd_provider.BlueDotsCallOutputProvider().compute(
                _call(), {}, client=client, now=end + timedelta(seconds=60))
        result = await bd_provider.BlueDotsCallOutputProvider().compute(
            _call(), {}, client=client, now=end + timedelta(seconds=settings.CALL_OUTPUT_LOG_GRACE_SECONDS + 1))
    assert result.output["applied"] is False and result.output["jobs_heard"] is False
    assert result.output["consent"] is None and result.output["last_phase"] is None


@pytest.mark.asyncio
async def test_provider_asks_the_llm_when_needed(bd_settings, monkeypatch):
    monkeypatch.setattr(settings, "CALL_OUTPUT_LLM_BASE_URL", LLM_URL)
    monkeypatch.setattr(settings, "CALL_OUTPUT_LLM_MODEL", "gpt-4.1-mini")
    monkeypatch.setattr(bd_provider, "_load_transcript", lambda call: [{"speaker": "caller", "text": "नहीं"}])
    rows = [_turn_line(SAMPLE_SESSION, "profile_resolve", 1), _tool_line(SAMPLE_SESSION, "fetch_jobs", True, 2),
            _turn_line(SAMPLE_SESSION, "job_match", 3)]
    now = datetime(2026, 11, 17, 13, 5, tzinfo=timezone.utc)
    async with _client_for(rows, '{"jobs_read_out": true, "drop_reason": "not_interested"}') as client:
        result = await bd_provider.BlueDotsCallOutputProvider().compute(_call(), {}, client=client, now=now)
    assert result.output["jobs_heard"] is True and result.output["drop_reason"] == "not_interested"
    assert result.signals["llm_model"] == "gpt-4.1-mini"
    async with _client_for(rows, "{}", llm_status=503) as client:
        with pytest.raises(CallOutputNotReady):
            await bd_provider.BlueDotsCallOutputProvider().compute(_call(), {}, client=client, now=now)


@pytest.mark.asyncio
async def test_provider_needs_a_loki_url(bd_settings, monkeypatch):
    monkeypatch.setattr(settings, "BLUEDOTS_LOKI_URL", "")
    async with _client_for([]) as client:
        with pytest.raises(RuntimeError, match="BLUEDOTS_LOKI_URL"):
            await bd_provider.BlueDotsCallOutputProvider().compute(_call(), {}, client=client)


# --------------------------------------------------------------- core ----


@pytest.fixture()
def db():
    return mongomock.MongoClient()["voicera_test"]


def _agent(db, *, call_output=True, webhook=False):
    config: dict[str, Any] = {}
    if call_output:
        config["call_output"] = {"enabled": True, "provider": "bluedots"}
    if webhook:
        config["webhook"] = {"enabled": True, "url": "https://hooks.example/x"}
    db["Agents"].insert_one({"agent_id": "agent-1", "org_id": "org-1", "config": config})


class _FakeProvider:
    name = "bluedots"

    def __init__(self, outcome):
        self.outcome = outcome

    async def compute(self, call, agent, *, client):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def test_schedule_answered_unanswered_and_opt_out(db):
    _agent(db)
    db["CallLogs"].insert_many([_call(), _call(call_id="c-busy", call_response="busy")])
    assert svc.schedule_for_call(db["CallLogs"].find_one({"call_id": SAMPLE_CALL_ID}), db=db) == "pending"
    assert svc.schedule_for_call(db["CallLogs"].find_one({"call_id": SAMPLE_CALL_ID}), db=db) is None
    row = db["CallLogs"].find_one({"call_id": SAMPLE_CALL_ID})
    assert row["call_output_status"] == "pending" and row["call_output_attempts"] == 0
    assert svc.schedule_for_call(db["CallLogs"].find_one({"call_id": "c-busy"}), db=db) == "skipped"
    busy = db["CallLogs"].find_one({"call_id": "c-busy"})
    assert busy["call_output"] == {}
    assert svc.schedule_for_call(_call(status="in_progress", call_id="live"), db=db) is None

    other = mongomock.MongoClient()["other"]
    _agent(other, call_output=False)
    other["CallLogs"].insert_one(_call())
    assert svc.schedule_for_call(other["CallLogs"].find_one({}), db=other) is None


def _make_due(db, call_id=SAMPLE_CALL_ID):
    db["CallLogs"].update_one({"call_id": call_id},
                              {"$set": {"call_output_due_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})


@pytest.mark.asyncio
async def test_dispatch_stores_ready_output(db):
    _agent(db)
    db["CallLogs"].insert_one(_call())
    svc.schedule_for_call(db["CallLogs"].find_one({}), db=db)
    assert svc.claim_due(limit=5, db=db) == []  # still within the delay
    _make_due(db)
    result = CallOutputResult(output={"applied": True}, signals={"phases": ["apply_confirm"]})
    with patch.object(svc, "get_provider", return_value=_FakeProvider(result)):
        async with httpx.AsyncClient() as client:
            assert await svc.dispatch_due(client=client, db=db) == 1
    row = db["CallLogs"].find_one({})
    assert row["call_output_status"] == "ready" and row["call_output"] == {"applied": True}
    assert row["call_output_signals"] == {"phases": ["apply_confirm"]} and row["call_output_error"] is None


@pytest.mark.asyncio
async def test_dispatch_retries_then_fails(db, monkeypatch):
    monkeypatch.setattr(settings, "CALL_OUTPUT_MAX_ATTEMPTS", 2)
    _agent(db)
    db["CallLogs"].insert_one(_call())
    svc.schedule_for_call(db["CallLogs"].find_one({}), db=db)
    with patch.object(svc, "get_provider", return_value=_FakeProvider(CallOutputNotReady("no logs yet"))):
        async with httpx.AsyncClient() as client:
            _make_due(db)
            await svc.dispatch_due(client=client, db=db)
            row = db["CallLogs"].find_one({})
            assert row["call_output_status"] == "pending" and row["call_output_attempts"] == 1
            assert "no logs yet" in row["call_output_error"]
            _make_due(db)
            await svc.dispatch_due(client=client, db=db)
    row = db["CallLogs"].find_one({})
    assert row["call_output_status"] == "failed" and row["call_output_attempts"] == 2


def test_call_log_patch_schedules_call_output_and_webhook(db, monkeypatch):
    monkeypatch.setattr(settings, "PROVIDER_AUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())
    _agent(db, webhook=True)
    db["CallLogs"].insert_one(_call(status="in_progress", call_response="pending"))
    with patch.object(call_log_service, "get_database", return_value=db):
        # what the runtime's finalize_call sends
        call_log_service.patch_call_log(
            "org-1", SAMPLE_CALL_ID, {"status": "completed", "call_response": "answered"})
    assert db["CallLogs"].find_one({})["call_output_status"] == "pending"
    assert db[wh.COLLECTION].count_documents({}) == 1


@pytest.mark.asyncio
async def test_hangup_before_answered_is_not_skipped(db):
    """Telephony hangup marks the call completed first; finalize_call marks it answered after."""
    _agent(db)
    db["CallLogs"].insert_one(_call(status="in_progress", call_response="pending"))
    with patch.object(call_log_service, "get_database", return_value=db):
        call_log_service.patch_call_log("org-1", SAMPLE_CALL_ID, {"status": "completed"})
        assert db["CallLogs"].find_one({})["call_output_status"] == "pending"
        call_log_service.patch_call_log("org-1", SAMPLE_CALL_ID, {"call_response": "answered"})
    _make_due(db)
    result = CallOutputResult(output={"applied": False})
    with patch.object(svc, "get_provider", return_value=_FakeProvider(result)):
        async with httpx.AsyncClient() as client:
            await svc.dispatch_due(client=client, db=db)
    assert db["CallLogs"].find_one({})["call_output_status"] == "ready"


@pytest.mark.asyncio
async def test_unknown_response_waits_then_skips(db, monkeypatch):
    monkeypatch.setattr(settings, "CALL_OUTPUT_MAX_ATTEMPTS", 2)
    _agent(db)
    db["CallLogs"].insert_one(_call(call_response="pending"))
    svc.schedule_for_call(db["CallLogs"].find_one({}), db=db)
    with patch.object(svc, "get_provider", side_effect=AssertionError("must not compute")):
        async with httpx.AsyncClient() as client:
            _make_due(db)
            await svc.dispatch_due(client=client, db=db)
            assert db["CallLogs"].find_one({})["call_output_status"] == "pending"
            _make_due(db)
            await svc.dispatch_due(client=client, db=db)
    row = db["CallLogs"].find_one({})
    assert row["call_output_status"] == "skipped" and row["call_output"] == {}


def test_skipped_call_is_revived_when_answered_arrives(db):
    _agent(db)
    db["CallLogs"].insert_one(_call(call_response="cancelled"))
    assert svc.schedule_for_call(db["CallLogs"].find_one({}), db=db) == "skipped"
    db["CallLogs"].update_one({}, {"$set": {"call_response": "answered"}})
    assert svc.schedule_for_call(db["CallLogs"].find_one({}), db=db) == "pending"
    assert svc.schedule_for_call(db["CallLogs"].find_one({}), db=db) is None


@pytest.mark.asyncio
async def test_webhook_waits_for_call_output_then_carries_it(db, monkeypatch):
    monkeypatch.setattr(settings, "PROVIDER_AUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())
    _agent(db, webhook=True)
    wh.rotate_agent_secret("org-1", "agent-1", db=db)
    db["CallLogs"].insert_one(_call())
    svc.schedule_for_call(db["CallLogs"].find_one({}), db=db)
    wh.schedule_for_call(db["CallLogs"].find_one({}), db=db, settle_seconds=0)
    bodies: list[dict[str, Any]] = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        row = await wh.deliver(db[wh.COLLECTION].find_one({}), client=client, db=db)
        assert row["state"] == "pending" and row["attempts"] == 0
        assert row["last_error"] == "waiting for call_output" and bodies == []

        db["CallLogs"].update_one({}, {"$set": {"call_output_status": "ready",
                                                "call_output": {"applied": True}}})
        row = await wh.deliver(db[wh.COLLECTION].find_one({}), client=client, db=db)
    assert row["state"] == "delivered"
    assert bodies[0]["data"]["call_output"] == {"applied": True}
    assert bodies[0]["data"]["call_output_status"] == "ready"


@pytest.mark.asyncio
async def test_webhook_stops_waiting_after_the_max_wait(db, monkeypatch):
    monkeypatch.setattr(settings, "PROVIDER_AUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())
    _agent(db, webhook=True)
    wh.rotate_agent_secret("org-1", "agent-1", db=db)
    db["CallLogs"].insert_one(_call())
    svc.schedule_for_call(db["CallLogs"].find_one({}), db=db)
    wh.schedule_for_call(db["CallLogs"].find_one({}), db=db, settle_seconds=0)
    old = datetime.now(timezone.utc) - timedelta(seconds=settings.CALL_OUTPUT_WEBHOOK_MAX_WAIT_SECONDS + 5)
    db[wh.COLLECTION].update_one({}, {"$set": {"created_at": old}})
    bodies: list[dict[str, Any]] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: bodies.append(json.loads(r.content)) or httpx.Response(200))) as client:
        row = await wh.deliver(db[wh.COLLECTION].find_one({}), client=client, db=db)
    assert row["state"] == "delivered" and bodies[0]["data"]["call_output_status"] == "pending"


def test_webhook_does_not_wait_for_agents_without_call_output():
    assert not svc.webhook_should_wait({"call_output_status": "pending"}, {"config": {}}, waiting_since=None)
    agent = {"config": {"call_output": {"enabled": True, "provider": "bluedots"}}}
    assert svc.webhook_should_wait({"call_output_status": "computing"}, agent, waiting_since=None)
    assert not svc.webhook_should_wait({"call_output_status": "ready"}, agent, waiting_since=None)
    assert not svc.webhook_should_wait({}, agent, waiting_since=None)


# ------------------------------------------------------ schema, routes ----


def test_call_output_schema_and_merge():
    assert AgentCallOutput().enabled is False
    with pytest.raises(ValueError):
        AgentCallOutput(enabled=True)
    with pytest.raises(ValueError):
        AgentCallOutput(enabled=True, provider="raya")
    from app.services import agent_service

    stack = {"stt_config": {"provider": "x"}, "tts_config": {"provider": "x"}, "llm_config": {"provider": "bluedots"}}
    base = {"prompts": {"system_prompt": "x", "greeting_message": "hi"},
            "language": {"primary": "hi", "secondary": []}, "models": {"hi": stack}}
    existing = AgentConfigPayload.model_validate(
        {**base, "call_output": {"enabled": True, "provider": "bluedots"}}).model_dump(mode="python")
    with patch.object(agent_service, "validate_agent_config", side_effect=lambda c, org_id: c):
        merged = agent_service._merge_config(existing, AgentConfigPayload.model_validate(base), org_id="org-1")
    assert merged.call_output.enabled is True and merged.call_output.provider == "bluedots"


def test_recompute_and_call_record_routes(db):
    _agent(db)
    db["CallLogs"].insert_many([
        _call(call_output_status="failed", call_output_error="boom", call_output={"x": 1}),
        _call(call_id="live", status="in_progress"),
    ])
    app = FastAPI()
    app.include_router(calls_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {"email": "a@x", "org_id": "org-1", "role": "member"}
    client = TestClient(app)
    with patch.object(svc, "get_database", return_value=db), \
         patch.object(call_log_service, "get_database", return_value=db):
        res = client.get(f"/api/v1/calls/{SAMPLE_CALL_ID}")
        assert res.status_code == 200
        assert res.json()["call_output_status"] == "failed" and res.json()["call_output"] == {"x": 1}
        res = client.post(f"/api/v1/calls/{SAMPLE_CALL_ID}/call-output/recompute")
        assert res.status_code == 202 and res.json()["call_output_status"] == "pending"
        assert client.post("/api/v1/calls/live/call-output/recompute").status_code == 409
