"""Unit tests for CallLogListFilters / build_call_log_query."""

from __future__ import annotations

from app.services.call_log_service import CallLogListFilters, build_call_log_query


def test_build_query_org_only() -> None:
    assert build_call_log_query("org-1") == {"org_id": "org-1"}


def test_build_query_campaign_id() -> None:
    q = build_call_log_query("org-1", CallLogListFilters(campaign_id="camp-1"))
    assert q == {"org_id": "org-1", "campaign_id": "camp-1"}


def test_build_query_exclude_campaign() -> None:
    q = build_call_log_query("org-1", CallLogListFilters(exclude_campaign=True))
    assert q["org_id"] == "org-1"
    assert "$or" in q
    assert {"campaign_id": {"$exists": False}} in q["$or"]
    assert {"campaign_id": None} in q["$or"]


def test_build_query_status_agent_type_response() -> None:
    q = build_call_log_query(
        "org-1",
        CallLogListFilters(
            agent_id="agent-1",
            status="completed",
            call_type="outbound",
            call_response="answered",
        ),
    )
    assert q == {
        "org_id": "org-1",
        "agent_id": "agent-1",
        "status": "completed",
        "call_type": "outbound",
        "call_response": "answered",
    }


def test_build_query_date_range() -> None:
    q = build_call_log_query(
        "org-1",
        CallLogListFilters(
            created_after="2026-01-01T00:00:00+00:00",
            created_before="2026-01-31T23:59:59+00:00",
        ),
    )
    assert q["created_at"] == {
        "$gte": "2026-01-01T00:00:00+00:00",
        "$lte": "2026-01-31T23:59:59+00:00",
    }


def test_exclude_campaign_wins_over_empty_campaign_id() -> None:
    """exclude_campaign should not set campaign_id equality."""
    q = build_call_log_query(
        "org-1",
        CallLogListFilters(exclude_campaign=True, campaign_id=None),
    )
    assert "campaign_id" not in q
    assert "$or" in q
