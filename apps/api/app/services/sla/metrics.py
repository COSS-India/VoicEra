"""Shared SLA metric response helpers."""

from __future__ import annotations

from typing import Any, Literal

MetricStatus = Literal["met", "missed", "no_data"]
OperatingStatus = Literal["working_normally", "not_working_normally", "unknown"]
MetricScope = Literal["campaign", "deployment"]


def nearest_rank_percentile(values: list[float], percentile: float) -> float | None:
    """Nearest-rank percentile, matching model-server benches (no interpolation)."""
    if not values:
        return None
    ordered = sorted(values)
    if percentile <= 0:
        return ordered[0]
    if percentile >= 1:
        return ordered[-1]
    index = max(0, min(len(ordered) - 1, int(percentile * len(ordered))))
    return ordered[index]


def compare_actual(
    actual: float | None,
    *,
    target: float,
    comparator: str,
) -> MetricStatus:
    if actual is None:
        return "no_data"
    if comparator in {"lte", "or_less", "<="}:
        return "met" if actual <= target else "missed"
    if comparator in {"gte", "or_more", ">="}:
        return "met" if actual >= target else "missed"
    if comparator in {"eq", "=="}:
        return "met" if actual == target else "missed"
    return "no_data"


def operating_from_status(status: MetricStatus) -> OperatingStatus:
    if status == "met":
        return "working_normally"
    if status == "missed":
        return "not_working_normally"
    return "unknown"


def metric(
    *,
    key: str,
    label: str,
    target: float,
    comparator: str,
    unit: str,
    actual: float | None,
    source: str,
    scope: MetricScope,
    sample_count: int | None = None,
    operating_status: OperatingStatus | None = None,
) -> dict[str, Any]:
    status = compare_actual(actual, target=target, comparator=comparator)
    row: dict[str, Any] = {
        "key": key,
        "label": label,
        "target": target,
        "comparator": comparator,
        "unit": unit,
        "actual": actual,
        "status": status,
        "operating_status": operating_status or operating_from_status(status),
        "source": source,
        "scope": scope,
    }
    if sample_count is not None:
        row["sample_count"] = sample_count
    return row


def no_data_metric(
    *,
    key: str,
    label: str,
    target: float,
    comparator: str,
    unit: str,
    source: str,
    scope: MetricScope,
) -> dict[str, Any]:
    return metric(
        key=key,
        label=label,
        target=target,
        comparator=comparator,
        unit=unit,
        actual=None,
        source=source,
        scope=scope,
    )
