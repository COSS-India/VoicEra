"""Incident-handling SLA targets. No incident store in this pass."""

from __future__ import annotations

from typing import Any

from app.services.sla import targets
from app.services.sla.metrics import no_data_metric


def collect_incidents() -> dict[str, Any]:
    metrics = [
        no_data_metric(
            key="incidents_notified_on_time",
            label="Incidents notified on time",
            target=targets.INCIDENT_ON_TIME_PCT,
            comparator="gte",
            unit="pct",
            source="no_incident_store",
            scope="deployment",
        ),
        no_data_metric(
            key="incidents_restored_on_time",
            label="Incidents restored on time",
            target=targets.INCIDENT_ON_TIME_PCT,
            comparator="gte",
            unit="pct",
            source="no_incident_store",
            scope="deployment",
        ),
        no_data_metric(
            key="root_cause_reports_on_time",
            label="Root cause reports on time",
            target=targets.INCIDENT_ON_TIME_PCT,
            comparator="gte",
            unit="pct",
            source="no_incident_store",
            scope="deployment",
        ),
        no_data_metric(
            key="requests_with_request_and_correlation_id",
            label="Requests with Request and Correlation ID",
            target=targets.INCIDENT_ON_TIME_PCT,
            comparator="gte",
            unit="pct",
            source="no_request_id_middleware",
            scope="deployment",
        ),
    ]
    for row in metrics:
        row["operating_status"] = "unknown"
    return {"scope": "deployment", "metrics": metrics}
