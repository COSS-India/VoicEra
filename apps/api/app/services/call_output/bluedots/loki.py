"""Read one call's AI DPG log lines from Loki's HTTP API."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LogLine:
    ts_ns: int
    labels: dict[str, str]
    record: dict[str, Any]  # the OTLP JSON line: body, traceid, attributes, …

    @property
    def attributes(self) -> dict[str, Any]:
        attrs = self.record.get("attributes")
        return attrs if isinstance(attrs, dict) else {}


def _ns(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def parse_line(ts_ns: Any, labels: dict[str, str], raw: str) -> LogLine | None:
    try:
        record = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    return LogLine(ts_ns=int(ts_ns), labels=dict(labels or {}), record=record)


def belongs_to_call(line: LogLine, call_id: str) -> bool:
    """A line is this call's when its ``session_id`` ends with ``:<call_id>``."""
    session_id = str(line.attributes.get("session_id") or "")
    return session_id.endswith(f":{call_id}")


async def fetch_call_lines(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    selector: str,
    call_id: str,
    start: datetime,
    end: datetime,
    timeout: float,
    limit: int = 5000,
) -> list[LogLine]:
    """All of a call's lines between ``start`` and ``end``, oldest first.

    The line filter on ``call_id`` keeps the query cheap; ``belongs_to_call``
    then drops any line that only mentions the id in passing.
    """
    escaped = call_id.replace("\\", "\\\\").replace('"', '\\"')
    params = {
        "query": f'{selector} |= "{escaped}"',
        "start": str(_ns(start)),
        "end": str(_ns(end)),
        "limit": str(limit),
        "direction": "forward",
    }
    url = base_url.rstrip("/") + "/loki/api/v1/query_range"
    response = await client.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    lines: list[LogLine] = []
    for stream in ((payload.get("data") or {}).get("result") or []):
        labels = stream.get("stream") or {}
        for value in stream.get("values") or []:
            if not isinstance(value, (list, tuple)) or len(value) < 2:
                continue
            line = parse_line(value[0], labels, value[1])
            if line is not None and belongs_to_call(line, call_id):
                lines.append(line)
    lines.sort(key=lambda item: item.ts_ns)
    if len(lines) >= limit:
        logger.warning("Loki returned %s lines for call_id=%s; results may be cut", len(lines), call_id)
    return lines
