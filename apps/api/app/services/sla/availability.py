"""Deployment availability targets with no stored probe history."""

from __future__ import annotations

from typing import Any

from app.services.sla import targets
from app.services.sla.metrics import no_data_metric


def collect_availability() -> dict[str, Any]:
    metrics = [
        no_data_metric(
            key="overall_availability",
            label="Overall availability",
            target=targets.OVERALL_AVAILABILITY_PCT,
            comparator="gte",
            unit="pct",
            source="no_health_history",
            scope="deployment",
        ),
        no_data_metric(
            key="peak_hours_availability",
            label="Peak-hours availability",
            target=targets.PEAK_AVAILABILITY_PCT,
            comparator="gte",
            unit="pct",
            source="no_health_history",
            scope="deployment",
        ),
        no_data_metric(
            key="unplanned_downtime",
            label="Unplanned downtime this month",
            target=targets.UNPLANNED_DOWNTIME_MIN_30D,
            comparator="lte",
            unit="min",
            source="no_health_history",
            scope="deployment",
        ),
        no_data_metric(
            key="health_check_success",
            label="Health check success",
            target=targets.HEALTH_CHECK_SUCCESS_PCT,
            comparator="gte",
            unit="pct",
            source="no_health_history",
            scope="deployment",
        ),
    ]
    return {"scope": "deployment", "metrics": metrics}
