"""SLA analytics route and collector tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import sla as sla_router
from app.services.campaign.campaign_repository import CampaignNotFoundError
from app.services.sla.metrics import nearest_rank_percentile
from app.services.sla.status_rules import (
    hosting_status,
    orchestrator_status,
    slot_status,
    telephony_status,
)


def _admin() -> dict[str, Any]:
    return {"email": "admin@example.com", "org_id": "org-1", "role": "admin"}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(sla_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _admin
    return TestClient(app)


def test_nearest_rank_percentile() -> None:
    values = [100.0, 200.0, 300.0, 400.0, 1000.0]
    assert nearest_rank_percentile(values, 0.95) == 1000.0
    assert nearest_rank_percentile(values, 0.50) == 300.0
    assert nearest_rank_percentile([], 0.95) is None


def test_hosting_status_rules() -> None:
    assert (
        hosting_status(
            nvidia_smi_available=False,
            gpu_count=None,
            nvidia_smi_failed=False,
            model_server_configured=False,
            gateway_reachable=None,
        )
        == "unknown"
    )
    assert (
        hosting_status(
            nvidia_smi_available=True,
            gpu_count=0,
            nvidia_smi_failed=False,
            model_server_configured=False,
            gateway_reachable=None,
        )
        == "not_working_normally"
    )
    assert (
        hosting_status(
            nvidia_smi_available=True,
            gpu_count=1,
            nvidia_smi_failed=False,
            model_server_configured=True,
            gateway_reachable=True,
        )
        == "working_normally"
    )


def test_slot_and_telephony_and_orchestrator_rules() -> None:
    assert telephony_status(configured=False, components_up=None) == "unknown"
    assert telephony_status(configured=True, components_up=True) == "working_normally"
    assert telephony_status(configured=True, components_up=False) == "not_working_normally"

    assert (
        slot_status(
            model_server_configured=True,
            slot={"deployed": True, "reachable": True},
            latest_has_stage_sample=None,
        )
        == "working_normally"
    )
    assert (
        slot_status(
            model_server_configured=True,
            slot={"deployed": True, "reachable": True},
            latest_has_stage_sample=False,
        )
        == "not_working_normally"
    )

    assert orchestrator_status(calls=[], metrics_by_call_id={}) == "unknown"
    assert (
        orchestrator_status(
            calls=[{"status": "in_progress", "call_id": "c1"}],
            metrics_by_call_id={},
        )
        == "working_normally"
    )


def test_campaign_not_found(client: TestClient) -> None:
    with patch(
        "app.services.sla.base_details.collector.load_campaign",
        side_effect=CampaignNotFoundError("camp-x"),
    ):
        response = client.get("/api/v1/sla/campaigns/camp-x/base-details")
    assert response.status_code == 404


def test_gpu_unavailable_when_nvidia_smi_missing(client: TestClient) -> None:
    with (
        patch("app.services.sla.gpu.sampler.shutil.which", return_value=None),
        patch(
            "app.services.sla.gpu.sampler.record_sample",
            return_value={"sample_id": "s1", "recorded_at": "t", "healthy": False},
        ),
        patch(
            "app.services.sla.gpu.sampler.aggregate_gpu_history",
            return_value={
                "sample_count": 0,
                "health_check_success_pct": None,
                "healthy_gpu_uptime_pct": None,
                "peak_utilization_pct": None,
                "peak_above_threshold_seconds": None,
                "window_seconds": 86400,
            },
        ),
        patch("app.services.sla.gpu.sampler.latest_ready_restart", return_value=None),
        patch("app.services.sla.gpu.sampler.open_restart", return_value=None),
    ):
        response = client.get("/api/v1/sla/gpu")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "unavailable"
    by_key = {m["key"]: m for m in body["metrics"]}
    assert by_key["health_check_success"]["target"] == 99.9
    assert by_key["health_check_success"]["status"] == "no_data"
    assert by_key["peak_gpu_load"]["status"] == "no_data"
    assert by_key["model_ready_after_restart"]["status"] == "no_data"


def test_gpu_with_history_and_peak(client: TestClient) -> None:
    live = {
        "available": True,
        "failed": False,
        "reason": None,
        "gpus": [
            {
                "index": 0,
                "uuid": "gpu-0",
                "name": "H200",
                "utilization_gpu_pct": 85.0,
                "utilization_memory_pct": 40.0,
                "memory_used_mib": 1000.0,
                "memory_total_mib": 140000.0,
                "temperature_c": 50.0,
                "power_draw_w": 200.0,
            }
        ],
    }
    with (
        patch("app.services.sla.gpu.sampler.run_nvidia_smi", return_value=live),
        patch(
            "app.services.sla.gpu.sampler.record_sample",
            return_value={"sample_id": "s1", "recorded_at": "t", "healthy": True},
        ),
        patch(
            "app.services.sla.gpu.sampler.aggregate_gpu_history",
            return_value={
                "sample_count": 12,
                "health_check_success_pct": 99.95,
                "healthy_gpu_uptime_pct": 99.95,
                "peak_utilization_pct": 85.0,
                "peak_above_threshold_seconds": 25.0,
                "window_seconds": 86400,
            },
        ),
        patch(
            "app.services.sla.gpu.sampler.latest_ready_restart",
            return_value={"ready_secs": 180.0},
        ),
        patch("app.services.sla.gpu.sampler.open_restart", return_value=None),
        patch("app.services.sla.gpu.sampler.mark_restart_ready", return_value=None),
    ):
        response = client.get("/api/v1/sla/gpu")
    assert response.status_code == 200
    by_key = {m["key"]: m for m in response.json()["metrics"]}
    assert by_key["health_check_success"]["actual"] == 99.95
    assert by_key["health_check_success"]["status"] == "met"
    assert by_key["peak_gpu_load"]["actual"] == 85.0
    assert by_key["peak_gpu_load"]["status"] == "missed"
    assert by_key["peak_gpu_load_duration"]["actual"] == 25.0
    assert by_key["model_ready_after_restart"]["actual"] == 3.0
    assert by_key["model_ready_after_restart"]["status"] == "met"


def test_inference_met_and_missed_p95(client: TestClient) -> None:
    campaign = {"campaign_id": "camp-1", "name": "Mahavistar"}
    calls = [{"call_id": "c1", "status": "completed"}]
    metrics_docs = [
        {
            "call_id": "c1",
            "recorded_at": "2026-11-16T10:00:00+00:00",
            "latencies": {
                "breakdowns": [
                    {
                        "user_turn_start_time": 1.0,
                        "ttfb": [
                            {"stage": "stt", "duration_secs": 0.4},
                            {"stage": "llm", "duration_secs": 0.5},
                            {"stage": "tts", "duration_secs": 0.2},
                        ],
                    },
                    {
                        "user_turn_start_time": 2.0,
                        "ttfb": [
                            {"stage": "stt", "duration_secs": 2.0},
                            {"stage": "llm", "duration_secs": 0.6},
                            {"stage": "tts", "duration_secs": 0.3},
                        ],
                    },
                ]
            },
        }
    ]
    with (
        patch(
            "app.services.sla.telemetry.inference.load_campaign",
            return_value=campaign,
        ),
        patch(
            "app.services.sla.telemetry.inference.list_campaign_calls",
            return_value=calls,
        ),
        patch(
            "app.services.sla.telemetry.inference.list_campaign_metrics",
            return_value=metrics_docs,
        ),
        patch(
            "app.services.sla.telemetry.inference.fetch_gateway_health",
            return_value={"configured": False, "reachable": None, "upstreams": {}},
        ),
    ):
        response = client.get("/api/v1/sla/campaigns/camp-1/inference")
    assert response.status_code == 200
    body = response.json()
    assert body["campaign_id"] == "camp-1"
    by_key = {m["key"]: m for m in body["metrics"]}
    # Two samples: 400 and 2000 → p95 is 2000 → missed vs 1000
    assert by_key["stt_p95"]["actual"] == 2000.0
    assert by_key["stt_p95"]["status"] == "missed"
    assert by_key["tts_p95"]["status"] == "met"
    assert by_key["error_rate"]["status"] == "no_data"


def test_inference_no_samples(client: TestClient) -> None:
    with (
        patch(
            "app.services.sla.telemetry.inference.load_campaign",
            return_value={"campaign_id": "camp-1", "name": "Empty"},
        ),
        patch(
            "app.services.sla.telemetry.inference.list_campaign_calls",
            return_value=[],
        ),
        patch(
            "app.services.sla.telemetry.inference.list_campaign_metrics",
            return_value=[],
        ),
        patch(
            "app.services.sla.telemetry.inference.fetch_gateway_health",
            return_value={"configured": False, "reachable": None, "upstreams": {}},
        ),
    ):
        response = client.get("/api/v1/sla/campaigns/camp-1/inference")
    assert response.status_code == 200
    by_key = {m["key"]: m for m in response.json()["metrics"]}
    assert by_key["stt_p95"]["status"] == "no_data"


def test_telephony_unconfigured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEPHONY_SLA_BASE_URL", raising=False)
    monkeypatch.delenv("TELEPHONY_SLA_TOKEN", raising=False)
    response = client.get("/api/v1/sla/telephony")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "telephony_unconfigured"
    assert all(m["status"] == "no_data" for m in body["metrics"])
    assert all(m["operating_status"] == "unknown" for m in body["metrics"])


def test_telephony_configured_stub(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEPHONY_SLA_BASE_URL", "https://tel.example")
    monkeypatch.setenv("TELEPHONY_SLA_TOKEN", "secret")

    def fake_get(path: str) -> dict[str, Any] | None:
        if path.startswith("/v1/availability"):
            return {
                "availability_pct": 99.95,
                "peak_hours_availability_pct": 99.97,
                "websocket_up": True,
                "number_up": True,
                "gateway_up": True,
                "status": "up",
            }
        if path.startswith("/v1/capacity"):
            return {"reserved_connections": 900}
        if path.startswith("/v1/media"):
            return {
                "summary": {
                    "post_dial_delay_p95_s": 2.1,
                    "connection_time_p95_ms": 380,
                    "one_way_media_delay_ms": 112,
                    "jitter_ms": 18,
                    "packet_loss_pct": 0.3,
                    "mos": 4.1,
                    "carrier_side_call_drops_pct": 0.3,
                    "call_setup_success_pct": 99.4,
                }
            }
        return None

    with patch(
        "app.services.sla.telephony.client._provider_get",
        side_effect=fake_get,
    ):
        response = client.get("/api/v1/sla/telephony")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    by_key = {m["key"]: m for m in body["metrics"]}
    assert by_key["telephony_availability"]["status"] == "met"
    assert by_key["audio_quality_mos"]["actual"] == 4.1


def test_base_details_pipeline_and_statuses(client: TestClient) -> None:
    campaign = {"campaign_id": "camp-1", "name": "Mahavistar"}
    calls = [
        {
            "call_id": "c1",
            "status": "in_progress",
            "call_response": "answered",
            "updated_at": "2026-11-16T10:41:00+00:00",
            "start_time_utc": "2026-11-16T10:40:00+00:00",
        }
    ]
    metrics_docs = [
        {
            "call_id": "c1",
            "recorded_at": "2026-11-16T10:41:30+00:00",
            "latencies": {
                "breakdowns": [
                    {
                        "user_turn_start_time": 1.0,
                        "ttfb": [
                            {"stage": "llm", "duration_secs": 0.5},
                            {"stage": "tts", "duration_secs": 0.2},
                        ],
                    }
                ]
            },
        }
    ]
    with (
        patch(
            "app.services.sla.base_details.collector.load_campaign",
            return_value=campaign,
        ),
        patch(
            "app.services.sla.base_details.collector.list_campaign_calls",
            return_value=calls,
        ),
        patch(
            "app.services.sla.base_details.collector.list_campaign_metrics",
            return_value=metrics_docs,
        ),
        patch(
            "app.services.sla.base_details.collector.run_nvidia_smi",
            return_value={
                "available": False,
                "failed": False,
                "gpus": [],
                "reason": "nvidia-smi not on PATH",
            },
        ),
        patch(
            "app.services.sla.base_details.collector.fetch_gateway_health",
            return_value={
                "configured": False,
                "reachable": None,
                "upstreams": {},
            },
        ),
        patch(
            "app.services.sla.base_details.collector.model_server_base_url",
            return_value=None,
        ),
        patch(
            "app.services.sla.base_details.collector.telephony_configured",
            return_value=False,
        ),
        patch(
            "app.services.sla.base_details.collector.provider_components_up",
            return_value=None,
        ),
        patch(
            "app.services.sla.base_details.collector.upsert_component_state",
            side_effect=lambda **kwargs: {
                "component_id": kwargs["component_id"],
                "status": kwargs["status"],
                "since": "2026-11-16T10:41:00+00:00",
                "updated_at": "2026-11-16T10:41:00+00:00",
            },
        ),
    ):
        response = client.get("/api/v1/sla/campaigns/camp-1/base-details")
    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_last_active_at"] is not None
    by_id = {s["id"]: s for s in body["services"]}
    assert by_id["hosting"]["status"] == "unknown"
    assert by_id["telephony"]["status"] == "unknown"
    # In-progress campaign call → STT/LLM/TTS are running.
    assert by_id["stt"]["status"] == "running"
    assert by_id["llm"]["status"] == "running"
    assert by_id["tts"]["status"] == "running"
    assert by_id["stt"]["call_happened"] == "in progress"
    assert by_id["orchestrator"]["status"] == "working"
    assert by_id["orchestrator"]["active_since"] is not None
    assert by_id["orchestrator"]["down_since"] is None


def test_base_details_pipeline_idle_shows_call_ago(client: TestClient) -> None:
    campaign = {"campaign_id": "camp-1", "name": "Mahavistar"}
    calls = [
        {
            "call_id": "c1",
            "status": "completed",
            "call_response": "answered",
            "end_time_utc": "2026-11-16T10:00:00+00:00",
            "start_time_utc": "2026-11-16T09:59:00+00:00",
        }
    ]
    with (
        patch(
            "app.services.sla.base_details.collector.load_campaign",
            return_value=campaign,
        ),
        patch(
            "app.services.sla.base_details.collector.list_campaign_calls",
            return_value=calls,
        ),
        patch(
            "app.services.sla.base_details.collector.list_campaign_metrics",
            return_value=[],
        ),
        patch(
            "app.services.sla.base_details.collector.run_nvidia_smi",
            return_value={
                "available": False,
                "failed": False,
                "gpus": [],
                "reason": "nvidia-smi not on PATH",
            },
        ),
        patch(
            "app.services.sla.base_details.collector.fetch_gateway_health",
            return_value={"configured": False, "reachable": None, "upstreams": {}},
        ),
        patch(
            "app.services.sla.base_details.collector.model_server_base_url",
            return_value=None,
        ),
        patch(
            "app.services.sla.base_details.collector.telephony_configured",
            return_value=False,
        ),
        patch(
            "app.services.sla.base_details.collector.provider_components_up",
            return_value=None,
        ),
        patch(
            "app.services.sla.base_details.collector.upsert_component_state",
            side_effect=lambda **kwargs: {
                "component_id": kwargs["component_id"],
                "status": kwargs["status"],
                "since": "2026-11-16T10:00:00+00:00",
                "updated_at": "2026-11-16T10:00:00+00:00",
            },
        ),
    ):
        response = client.get("/api/v1/sla/campaigns/camp-1/base-details")
    assert response.status_code == 200
    by_id = {s["id"]: s for s in response.json()["services"]}
    assert by_id["stt"]["status"] == "not_running"
    assert by_id["stt"]["call_happened"].startswith("call happened:")
    assert by_id["stt"]["call_happened_ago_seconds"] is not None
    assert by_id["llm"]["status"] == "not_running"
    assert by_id["tts"]["status"] == "not_running"


def test_telemetry_aggregates_capacity_and_inference(client: TestClient) -> None:
    with (
        patch(
            "app.services.sla.telemetry.aggregate.collect_inference",
            return_value={
                "campaign_name": "Mahavistar",
                "call_count": 2,
                "metrics": [{"key": "stt_p95", "actual": 400}],
                "gateway": {},
            },
        ),
        patch(
            "app.services.sla.telemetry.aggregate.collect_orchestration",
            return_value={"metrics": [{"key": "end_to_end_p95", "actual": 2000}]},
        ),
        patch(
            "app.services.sla.telemetry.aggregate.collect_capacity",
            new_callable=AsyncMock,
            return_value={
                "campaign_name": "Mahavistar",
                "call_count": 2,
                "metrics": [{"key": "calls_live_now", "actual": 1}],
            },
        ),
    ):
        response = client.get("/api/v1/sla/campaigns/camp-1/telemetry")
    assert response.status_code == 200
    body = response.json()
    assert body["campaign_id"] == "camp-1"
    keys = {m["key"] for m in body["metrics"]}
    assert "stt_p95" in keys
    assert "calls_live_now" in keys
    assert "end_to_end_p95" in keys


def test_orchestration_and_capacity_and_availability(client: TestClient) -> None:
    campaign = {"campaign_id": "camp-1", "name": "Mahavistar"}
    calls = [
        {"call_id": "c1", "status": "completed", "call_response": "answered"},
        {"call_id": "c2", "status": "failed", "call_response": "failed"},
    ]
    metrics_docs = [
        {
            "call_id": "c1",
            "latencies": {"user_to_bot_secs": [1.0, 2.0, 2.5]},
        }
    ]
    with (
        patch(
            "app.services.sla.telemetry.orchestration.load_campaign",
            return_value=campaign,
        ),
        patch(
            "app.services.sla.telemetry.orchestration.list_campaign_calls",
            return_value=calls,
        ),
        patch(
            "app.services.sla.telemetry.orchestration.list_campaign_metrics",
            return_value=metrics_docs,
        ),
    ):
        orch = client.get("/api/v1/sla/campaigns/camp-1/orchestration")
    assert orch.status_code == 200
    orch_body = orch.json()
    by_key = {m["key"]: m for m in orch_body["metrics"]}
    assert by_key["end_to_end_p95"]["status"] == "met"
    assert by_key["agent_session_start_success"]["actual"] == 50.0
    assert by_key["agent_session_start_success"]["operating_status"] == "not_working_normally"

    with (
        patch(
            "app.services.sla.telemetry.capacity.load_campaign",
            return_value=campaign,
        ),
        patch(
            "app.services.sla.telemetry.capacity.list_campaign_calls",
            return_value=calls,
        ),
        patch(
            "app.services.sla.telemetry.capacity.live_calls_for_campaign",
            new_callable=AsyncMock,
            return_value=2,
        ),
    ):
        cap = client.get("/api/v1/sla/campaigns/camp-1/capacity")
    assert cap.status_code == 200
    cap_body = cap.json()
    live = next(m for m in cap_body["metrics"] if m["key"] == "calls_live_now")
    assert live["actual"] == 2.0

    avail = client.get("/api/v1/sla/availability")
    assert avail.status_code == 200
    assert all(m["status"] == "no_data" for m in avail.json()["metrics"])

    incidents = client.get("/api/v1/sla/incidents")
    assert incidents.status_code == 200
    assert all(m["status"] == "no_data" for m in incidents.json()["metrics"])


def test_campaign_other_org_404_on_inference(client: TestClient) -> None:
    with patch(
        "app.services.sla.telemetry.inference.load_campaign",
        side_effect=CampaignNotFoundError("camp-other"),
    ):
        response = client.get("/api/v1/sla/campaigns/camp-other/inference")
    assert response.status_code == 404
