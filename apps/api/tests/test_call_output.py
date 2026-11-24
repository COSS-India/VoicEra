"""Post-call call_output: Blue Dots adapter (KKB Slim output from AI DPG) and the core."""

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
from app.services.call_output.bluedots import llm, loki, provider as bd_provider, schema
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


def _facts(**kw) -> schema.CallFacts:
    facts = schema.CallFacts(seeker_name="Ravi", input_location="Hubli", caller_turns=5)
    for key, value in kw.items():
        setattr(facts, key, value)
    return facts


JOB = {"job_id": "NA", "role": "Electrician", "company_name": "Sigmatek", "company_location": "Hubli",
       "salary_offered": "NA", "qualification_required": "ITI"}


def test_normalise_holds_the_llm_answer_to_the_spec():
    out = schema.normalise({
        "call_answered": "yes", "primary_topic": "job SEARCH", "user_intent": "Wants a job",
        "applications_count": "2", "jobs_offered_count": True,
        "jobs_recommended": [JOB, "Electrician at Sigmatek", {"role": "Helper"}],
        "jobs_failed_to_apply": "NA", "pin_code": "11002", "service_callback_slot": "other: after 6",
        "call_later_request": "Yes: evening", "drop_reason": "  ", "final_summary": None,
    })
    assert list(out) == list(schema.FIELDS)  # every field, in the spec's order
    assert out["call_answered"] == "Yes" and out["primary_topic"] == "Job search"
    assert out["user_intent"] == "NA"  # off-spec value
    assert out["applications_count"] == 2 and out["jobs_offered_count"] == 0
    assert out["jobs_recommended"][0] == JOB and len(out["jobs_recommended"]) == 2
    assert out["jobs_recommended"][1]["company_name"] == "NA"
    assert out["jobs_failed_to_apply"] == [] and out["pin_code"] == "NA"  # never repaired
    assert out["service_callback_slot"] == "Other: after 6"
    assert out["call_later_request"] == "Yes: evening"
    assert out["drop_reason"] == "NA" and out["final_summary"] == "NA"
    assert schema.normalise("not a dict")["jobs_applied"] == []


def test_facts_override_what_the_tools_settle():
    llm_said = schema.normalise({
        "seeker_name": "Someone", "call_answered": "No", "call_engaged": "Yes",
        "applied_to_job": "Yes", "applications_count": 3, "jobs_applied": [JOB, JOB, JOB],
        "jobs_failed_to_apply": [{**JOB, "failure_reason": "x"}], "ready_for_interview": "Yes",
        "jobs_fetched": "Recommended", "consent_status": "Declined", "input_location_had_jobs": "Yes",
        "services_pitched": "Yes", "service_offered": "Made Up Trust", "service_interest": "Yes",
        "preference_mismatch_reason": "Location",
    })
    facts = _facts(calls={"fetch_jobs": 1, "save_profile": 2, "apply_job": 2},
                   successes={"fetch_jobs": 1, "save_profile": 1, "apply_job": 2},
                   failures={"save_profile": 1})
    out, sources = schema.apply_facts(llm_said, facts)
    assert out["seeker_name"] == "Ravi" and out["call_answered"] == "Yes" and out["call_engaged"] == "Yes"
    assert out["applied_to_job"] == "Yes" and out["applications_count"] == 2
    assert len(out["jobs_applied"]) == 2 and out["jobs_failed_to_apply"] == []
    assert out["ready_for_interview"] == "Yes"
    assert out["jobs_fetched"] == "Search" and out["consent_status"] == "Given"
    assert out["input_location_had_jobs"] == "NA"  # the job list is not in the logs
    assert out["service_offered"] == "NA" and out["service_interest"] == "Yes"
    assert out["preference_mismatch_reason"] == "NA"
    assert sources["applications_count"] == "apply_job tool calls"
    assert sources["service_offered"] == "no successful fetch_services"


def test_facts_without_jobs_applications_or_services():
    llm_said = schema.normalise({
        "call_engaged": "Yes", "jobs_shown": "Yes", "jobs_recommended": [JOB], "jobs_offered_count": 1,
        "job_roles_offered": "Electrician", "ready_for_interview": "No", "services_pitched": "No",
        "service_interest": "Maybe", "service_need_matched": "Training",
    })
    out, _ = schema.apply_facts(llm_said, _facts(caller_turns=2, phases=["consent", "consent_declined"]))
    assert out["call_engaged"] == "No"  # fewer than three caller turns
    assert out["jobs_fetched"] == "No" and out["jobs_shown"] == "No"
    assert out["jobs_recommended"] == [] and out["jobs_offered_count"] == 0 and out["job_roles_offered"] == "NA"
    assert out["applied_to_job"] == "No" and out["ready_for_interview"] == "NA"
    assert out["consent_status"] == "Declined"
    assert out["service_interest"] == "NA" and out["service_need_matched"] == "NA"
    out, _ = schema.apply_facts(schema.normalise({}), _facts(calls={"fetch_profile": 1}))
    assert out["consent_status"] == "NA"  # returning caller: no consent gate


def test_unanswered_output_and_inputs():
    call = {"custom_variables": {"contact_name": "Ravi", "location": "Hubli"}}
    out = schema.unanswered_output(schema.seeker_name_from(call))
    assert list(out) == list(schema.FIELDS)
    assert out["seeker_name"] == "Ravi" and out["call_answered"] == "No"
    assert out["primary_topic"] == "No engagement" and out["jobs_fetched"] == "No"
    assert out["jobs_applied"] == [] and out["applications_count"] == 0
    assert schema.input_location_from(call) == "Hubli"
    assert schema.seeker_name_from({}) == "Unknown"
    assert not schema.input_location_is_place("Any") and not schema.input_location_is_place("580020")


def test_spec_file_is_blue_dots_kkb_slim_output():
    text = llm.spec_text()
    assert "seeker_name" in text and "asked_job_location" in text and "EXAMPLE OUTPUT" in text
    for name in schema.FIELDS:
        assert name in text, name


def _gateway_line(session: str, tool: str, ts: int, *, body: str, level: str, status: str,
                  **extra: Any) -> dict[str, Any]:
    attrs = {"operation": "RestApiAdapter.execute", "session_id": session, "tool_name": tool,
             "status": status, **extra}
    return {"ts_ns": ts, "stream": {"job": "action_gateway", "level": level},
            "line": json.dumps({"body": body, "traceid": f"t{ts}", "attributes": attrs})}


def test_debug_logging_counts_each_tool_call_once():
    """At DEBUG, AI DPG logs request, response and session-values lines too (seen on the box)."""
    s = SAMPLE_SESSION
    rows = []
    for i, tool in enumerate(("fetch_profile", "apply_job")):
        base = (i + 1) * 100
        rows += [
            _gateway_line(s, tool, base + 1, body=f"rest_api_request tool={tool} method=GET", level="DEBUG",
                          status="pending", method="GET"),
            _gateway_line(s, tool, base + 2, body=f"rest_api_response tool={tool} status=200", level="DEBUG",
                          status="received", status_code=200, latency_ms=300),
            _gateway_line(s, tool, base + 3, body=f"rest_api_session_values tool={tool} keys=['x']",
                          level="INFO", status="success"),
            _gateway_line(s, tool, base + 4, body="rest_api_execute", level="INFO", status="success",
                          latency_ms=300),
        ]
    rows.append(_gateway_line(s, "apply_job", 900, body="rest_api_http_error tool=apply_job status=404",
                              level="WARN", status="failure", error="http_error: 404"))
    lines = [loki.parse_line(r["ts_ns"], r["stream"], r["line"]) for r in rows]
    signals = extract(lines)
    assert [(t.tool, t.ok) for t in signals.tools] == [
        ("fetch_profile", True), ("apply_job", True), ("apply_job", False),
    ]
    assert signals.succeeded("apply_job") == 1 and signals.failed("apply_job") == 1
    assert signals.tools[-1].error == "http_error: 404"


# ---------------------------------------------------------------- llm ----


def test_parse_output_is_strict_about_json():
    assert llm.parse_output('```json\n{"call_answered": "Yes"}\n```') == {"call_answered": "Yes"}
    with pytest.raises(llm.OutputParseError):
        llm.parse_output("no json here")
    with pytest.raises(llm.OutputParseError):
        llm.parse_output("{not json}")


@pytest.mark.asyncio
async def test_output_extractor_request():
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"call_engaged": "Yes"}'}}]})

    extractor = llm.OutputExtractor(base_url=LLM_URL, model="gpt-4.1-mini", api_key="k", timeout=5, json_mode=True)
    turns = [{"speaker": "agent", "text": "ನಮಸ್ಕಾರ"}, {"speaker": "caller", "text": "ಹೌದು ಕೆಲಸ ಬೇಕು"}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        raw = await extractor.extract(client, turns, inputs={"seeker_name": "Ravi", "location": "Hubli"},
                                      tool_calls=[{"tool": "fetch_jobs", "status": "success"}],
                                      phases=["job_match"])
    assert raw == {"call_engaged": "Yes"}
    assert seen["url"] == f"{LLM_URL}/chat/completions" and seen["auth"] == "Bearer k"
    body = seen["body"]
    assert body["model"] == "gpt-4.1-mini" and body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    system, user = body["messages"][0]["content"], body["messages"][1]["content"]
    assert system.endswith(llm.spec_text()) and "`save_profile` is create_profile" in system
    assert "CALLER: ಹೌದು ಕೆಲಸ ಬೇಕು" in user and '"location": "Hubli"' in user
    assert '"tool": "fetch_jobs"' in user


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
        "custom_variables": {"contact_name": "Ravi", "location": "Hubli"},
    }
    doc.update(extra)
    return doc


@pytest.fixture()
def bd_settings(monkeypatch):
    monkeypatch.setattr(settings, "BLUEDOTS_LOKI_URL", LOKI)
    monkeypatch.setattr(settings, "CALL_OUTPUT_LLM_BASE_URL", "")
    monkeypatch.setattr(settings, "CALL_OUTPUT_LLM_MODEL", "")
    monkeypatch.setattr(bd_provider, "_load_transcript", lambda call: [
        {"speaker": "agent", "text": "ನಮಸ್ಕಾರ"}, {"speaker": "caller", "text": "ಹೌದು"},
        {"speaker": "caller", "text": "ಕೆಲಸ ಬೇಕು"}, {"speaker": "caller", "text": "ಸರಿ"},
    ])


def _with_llm(monkeypatch):
    monkeypatch.setattr(settings, "CALL_OUTPUT_LLM_BASE_URL", LLM_URL)
    monkeypatch.setattr(settings, "CALL_OUTPUT_LLM_MODEL", "gpt-4.1-mini")


def _client_for(rows: list[dict[str, Any]], llm_reply: str | None = None, llm_status: int = 200,
                seen: dict[str, Any] | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "loki.test":
            return httpx.Response(200, json=_loki_payload(rows))
        if llm_reply is None:
            raise AssertionError("unexpected LLM call")
        if seen is not None:
            seen["user"] = json.loads(request.content)["messages"][1]["content"]
        return httpx.Response(llm_status, json={"choices": [{"message": {"content": llm_reply}}]})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_provider_computes_the_sample_call(bd_settings, monkeypatch):
    _with_llm(monkeypatch)
    llm_said = json.dumps({"call_engaged": "Yes", "primary_topic": "Job search",
                           "user_intent": "Job Application", "jobs_shown": "Yes",
                           "jobs_applied": [JOB], "drop_reason": "NA", "final_summary": "Applied."})
    seen: dict[str, Any] = {}
    async with _client_for(_fixture_rows(), llm_said, seen=seen) as client:
        result = await bd_provider.BlueDotsCallOutputProvider().compute(
            _call(), {}, client=client, now=datetime(2026, 11, 17, 13, 5, tzinfo=timezone.utc))
    out = result.output
    assert list(out) == list(schema.FIELDS)
    assert out["seeker_name"] == "Ravi" and out["call_answered"] == "Yes"
    assert out["applied_to_job"] == "Yes" and out["applications_count"] == 1 and out["jobs_applied"] == [JOB]
    assert out["consent_status"] == "Given" and out["jobs_fetched"] == "Search"
    assert out["user_intent"] == "Job Application" and out["final_summary"] == "Applied."
    assert result.signals["schema"] == schema.SCHEMA and result.signals["llm_model"] == "gpt-4.1-mini"
    assert result.signals["phases"][-1] == "apply_confirm"
    tools = json.loads(seen["user"].split("TOOL CALLS (in order)\n")[1].split("\n\n")[0])
    assert tools[3] == {"tool": "save_profile", "status": "failure", "error": "http_error: 400"}


@pytest.mark.asyncio
async def test_provider_waits_for_logs_then_accepts_none(bd_settings, monkeypatch):
    _with_llm(monkeypatch)
    end = datetime(2026, 11, 17, 13, 4, 2, tzinfo=timezone.utc)
    async with _client_for([], "{}") as client:
        with pytest.raises(CallOutputNotReady):
            await bd_provider.BlueDotsCallOutputProvider().compute(
                _call(), {}, client=client, now=end + timedelta(seconds=60))
        result = await bd_provider.BlueDotsCallOutputProvider().compute(
            _call(), {}, client=client, now=end + timedelta(seconds=settings.CALL_OUTPUT_LOG_GRACE_SECONDS + 1))
    assert result.output["applied_to_job"] == "No" and result.output["jobs_fetched"] == "No"
    assert result.output["consent_status"] == "NA"


@pytest.mark.asyncio
async def test_provider_silent_call_needs_no_llm(bd_settings, monkeypatch):
    monkeypatch.setattr(bd_provider, "_load_transcript", lambda call: [{"speaker": "agent", "text": "ನಮಸ್ಕಾರ"},
                                                                         {"speaker": "caller", "text": " ... "}])
    async with _client_for(_fixture_rows()) as client:
        result = await bd_provider.BlueDotsCallOutputProvider().compute(
            _call(), {}, client=client, now=datetime(2026, 11, 17, 13, 5, tzinfo=timezone.utc))
    assert result.output == schema.unanswered_output("Ravi")
    assert result.signals["llm_model"] is None


@pytest.mark.asyncio
async def test_provider_needs_llm_settings_and_retries_llm_failures(bd_settings, monkeypatch):
    now = datetime(2026, 11, 17, 13, 5, tzinfo=timezone.utc)
    async with _client_for(_fixture_rows()) as client:
        with pytest.raises(RuntimeError, match="CALL_OUTPUT_LLM"):
            await bd_provider.BlueDotsCallOutputProvider().compute(_call(), {}, client=client, now=now)
    _with_llm(monkeypatch)
    async with _client_for(_fixture_rows(), "{}", llm_status=503) as client:
        with pytest.raises(CallOutputNotReady):
            await bd_provider.BlueDotsCallOutputProvider().compute(_call(), {}, client=client, now=now)
    async with _client_for(_fixture_rows(), "sorry, I can't") as client:
        with pytest.raises(CallOutputNotReady, match="no JSON"):
            await bd_provider.BlueDotsCallOutputProvider().compute(_call(), {}, client=client, now=now)


@pytest.mark.asyncio
async def test_provider_gives_the_model_tool_arguments_not_results_and_keeps_only_real_job_ids(
        bd_settings, monkeypatch):
    """A cut-off job list made the model list jobs nobody offered (box, 2026-11-24): results stay out."""
    _with_llm(monkeypatch)
    s = SAMPLE_SESSION
    jobs = json.dumps({"message": {"items": [{"item_id": "job-unspoken", "item_state": {
        "role": "Electrician | Turner", "jobProviderName": "GTC Hubbali"}}]}})
    rows = [
        _gateway_line(s, "fetch_profile", 0, body="rest_api_request tool=fetch_profile method=GET",
                      level="DEBUG", status="pending", params={"phone_number": "919900000001"}),
        _gateway_line(s, "fetch_profile", 0, body="rest_api_execute", level="INFO", status="success"),
        _gateway_line(s, "fetch_jobs", 1, body="rest_api_request tool=fetch_jobs method=POST", level="DEBUG",
                      status="pending", params={"query_text": "Electrical jobs in Hubli"}),
        _gateway_line(s, "fetch_jobs", 2, body="rest_api_response tool=fetch_jobs status=200", level="DEBUG",
                      status="received", status_code=200),
        _gateway_line(s, "fetch_jobs", 3, body="rest_api_execute", level="INFO", status="success"),
        _gateway_line(s, "apply_job", 4, body="rest_api_request tool=apply_job method=POST", level="DEBUG",
                      status="pending", params={"job_id": "job-applied-1"}),
        _gateway_line(s, "apply_job", 5, body="rest_api_execute", level="INFO", status="success"),
    ]
    for i, row in enumerate(rows):  # one trace per tool call, as AI DPG logs it
        line = json.loads(row["line"])
        line["traceid"] = "trace-profile" if i < 2 else "trace-jobs" if i < 5 else "trace-apply"
        if i == 3:
            line["attributes"]["body"] = jobs
        row["line"] = json.dumps(line)
    job = {"role": "Machine Operator", "company_name": "Mycon Engineers", "company_location": "Hubli",
           "salary_offered": "NA", "qualification_required": "NA"}
    reply = json.dumps({
        "jobs_recommended": [{**job, "job_id": "job-unspoken"}, {**job, "job_id": "job-made-up"}],
        "jobs_applied": [{**job, "job_id": "job-applied-1"}],
    })
    seen: dict[str, Any] = {}
    async with _client_for(rows, reply, seen=seen) as client:
        result = await bd_provider.BlueDotsCallOutputProvider().compute(
            _call(), {}, client=client, now=datetime(2026, 11, 17, 13, 5, tzinfo=timezone.utc))
    tools = json.loads(seen["user"].split("TOOL CALLS (in order)\n")[1].split("\n\n")[0])
    assert tools == [
        {"tool": "fetch_profile", "status": "success"},
        {"tool": "fetch_jobs", "status": "success"},
        {"tool": "apply_job", "status": "success", "arguments": {"job_id": "job-applied-1"}},
    ]
    # No job list, and none of the caller's details, reach the model.
    assert "job-unspoken" not in seen["user"] and "919900000001" not in seen["user"]
    assert [j["job_id"] for j in result.output["jobs_recommended"]] == ["NA", "NA"]
    assert [j["job_id"] for j in result.output["jobs_applied"]] == ["job-applied-1"]
    assert result.signals["sources"]["jobs_recommended"] == "job_id not in any tool call: reset to NA"


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
    assert busy["call_output"] == schema.unanswered_output("Ravi")
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
    class _NoCompute(bd_provider.BlueDotsCallOutputProvider):
        async def compute(self, *args, **kwargs):
            raise AssertionError("must not compute")

    with patch.object(svc, "get_provider", return_value=_NoCompute()):
        async with httpx.AsyncClient() as client:
            _make_due(db)
            await svc.dispatch_due(client=client, db=db)
            assert db["CallLogs"].find_one({})["call_output_status"] == "pending"
            _make_due(db)
            await svc.dispatch_due(client=client, db=db)
    row = db["CallLogs"].find_one({})
    assert row["call_output_status"] == "skipped" and row["call_output"]["call_answered"] == "No"


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


def test_recompute_of_an_unanswered_call_writes_the_unanswered_output(db):
    _agent(db)
    db["CallLogs"].insert_one(_call(call_response="no_answer", call_output_status="failed"))
    row = svc.recompute("org-1", SAMPLE_CALL_ID, db=db)
    assert row["call_output_status"] == "skipped"
    assert row["call_output"] == schema.unanswered_output("Ravi")


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
