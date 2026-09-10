"""Tests for CallMetricsWriter aggregation and persistence."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.runtime.services.pipecat.metrics.writer import CallMetricsWriter


def test_writer_summary_aggregates_turns_and_latencies() -> None:
    writer = CallMetricsWriter(
        org_id="org-1",
        call_id="call-1",
        session_label="call_sid=sid",
    )
    writer.record_transport_report(
        type(
            "Report",
            (),
            {
                "start_time": 1.0,
                "bot_connected_secs": None,
                "client_connected_secs": 0.4,
            },
        )()
    )
    writer.record_user_bot_latency(1.0)
    writer.record_user_bot_latency(2.0)
    writer.record_turn_ended(1, 12.5, False)
    writer.record_turn_ended(2, 8.0, True)

    payload = writer.to_dict()
    assert set(payload.keys()) == {"summary", "transport", "turns", "latencies"}
    assert payload["summary"]["turn_count"] == 2
    assert payload["summary"]["interrupted_turn_count"] == 1
    assert payload["summary"]["user_bot_latency_avg_secs"] == 1.5
    assert payload["transport"]["client_connected_secs"] == 0.4


def test_writer_stamps_stage_from_pipeline_roles() -> None:
    writer = CallMetricsWriter(
        org_id="org-1",
        call_id="call-1",
        session_label="session",
        processor_stages={
            "BhashiniNemotronSTTService#2": "stt",
            "OpenAILLMService#4": "llm",
            "BhashiniOrpheusTTSService#2": "tts",
        },
    )
    writer.record_latency_breakdown(
        type(
            "Breakdown",
            (),
            {
                "model_dump": lambda self: {
                    "ttfb": [
                        {
                            "processor": "BhashiniOrpheusTTSService#2",
                            "duration_secs": 0.4,
                        },
                        {
                            "processor": "BhashiniNemotronSTTService#2",
                            "duration_secs": 0.5,
                        },
                    ],
                    "user_turn_start_time": 1.0,
                },
            },
        )()
    )

    entries = writer.to_dict()["latencies"]["breakdowns"][0]["ttfb"]
    assert entries[0]["stage"] == "tts"
    assert entries[1]["stage"] == "stt"


@pytest.mark.asyncio
async def test_flush_skips_without_content() -> None:
    writer = CallMetricsWriter(
        org_id="org-1",
        call_id="call-1",
        session_label="session",
    )
    with patch(
        "apps.runtime.services.pipecat.metrics.writer.backend_client.upsert_call_metrics",
        new_callable=AsyncMock,
    ) as upsert_metrics:
        await writer.flush()
        upsert_metrics.assert_not_called()


@pytest.mark.asyncio
async def test_flush_upserts_metrics_once() -> None:
    writer = CallMetricsWriter(
        org_id="org-1",
        call_id="call-1",
        session_label="session",
    )
    writer.record_user_bot_latency(0.75)

    with patch(
        "apps.runtime.services.pipecat.metrics.writer.backend_client.upsert_call_metrics",
        new_callable=AsyncMock,
    ) as upsert_metrics:
        await writer.flush()
        upsert_metrics.assert_awaited_once()
        args = upsert_metrics.await_args
        assert args.args[0] == "call-1"
        assert args.args[1] == "org-1"
        assert args.args[2]["summary"]["turn_count"] == 0

        await writer.flush()
        upsert_metrics.assert_awaited_once()
