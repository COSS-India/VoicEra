"""VI pull-call-details client and row mapping.

Separate from OBD AuthToken. Credentials are the Pull API username and password.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import httpx

from .auth_helpers import normalize_msisdn

PULL_BASE = "https://cts.myvi.in:8443/Cpaas/api/v1/pullcalldetails"
# 2 = outbound detail. 1 inbound, 3 click-to-call, 4 outbound summary.
OBD_PULL_CALLTYPE = "2"
REQUEST_TIMEOUT_SECS = 60
IST = ZoneInfo("Asia/Kolkata")
_A_PARTY_NO_KEYS = (" A PARTY NO", "A PARTY NO")
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")


class ViPullReportError(Exception):
    """Pull-report auth or fetch failed."""

    def __init__(self, message: str, *, code: str = "provider_error") -> None:
        super().__init__(message)
        self.code = code


def pull_base_from_obd_base(obd_base: str) -> str:
    base = (obd_base or "").strip().rstrip("/")
    suffix = "/obdcampaignapi"
    if base.endswith(suffix):
        return base[: -len(suffix)] + "/pullcalldetails"
    return PULL_BASE


def _parse_date(value: str) -> datetime | None:
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(IST).replace(tzinfo=None)
    return parsed


def _format_pull_date(value: datetime) -> str:
    return value.strftime("%d/%m/%Y")


def resolve_pull_window(
    fromdate: str | None,
    todate: str | None,
    started_at: str | None,
    *,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Return ``DD/MM/YYYY`` bounds for pullreport."""
    current = now or datetime.now(IST)
    if current.tzinfo is not None:
        current = current.astimezone(IST).replace(tzinfo=None)
    today = _format_pull_date(current)

    start = _parse_date(fromdate) if fromdate else None
    end = _parse_date(todate) if todate else None
    if start is None and started_at:
        start = _parse_date(started_at)
    if start is None:
        start_text = today
    else:
        start_text = _format_pull_date(start)
    if end is None:
        end_text = today
    else:
        end_text = _format_pull_date(end)
    return start_text, end_text


def _party_number(row: Mapping[str, Any]) -> str | None:
    for key in _A_PARTY_NO_KEYS:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _duration_seconds(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _recording_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.lower().startswith("http"):
        return text
    return None


def map_pull_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Map one pullreport object onto the API row shape."""
    dial_date = row.get("A PARTY DIAL START DATE")
    dial_time = row.get("A PARTY DIAL START TIME")
    when: str | None = None
    if dial_date and dial_time:
        when = f"{dial_date} {dial_time}"
    elif dial_date:
        when = str(dial_date)

    call_id = row.get("CALL ID")
    campaign_id = row.get("CAMPAIGN ID")
    return {
        "provider_call_id": None if call_id is None else str(call_id),
        "phone": _party_number(row),
        "dial_status": row.get("A PARTY DIAL STATUS") or None,
        "when": when,
        "duration_seconds": _duration_seconds(row.get("TOTAL DURATION(In Seconds)")),
        "recording_url": _recording_url(row.get("RECORD")),
        "circle": row.get("CALLER CIRCLE") or None,
        "operator": row.get("CALLER OPERATOR") or None,
        "campaign_id": None if campaign_id is None else str(campaign_id),
        "campaign_name": row.get("CAMPAIGN NAME") or None,
    }


def summarize_rows(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    attempted = len(rows)
    connected_durations: list[float] = []
    connected = timeout = line_drop = 0
    for row in rows:
        status = str(row.get("dial_status") or "").strip().lower()
        if status == "connected":
            connected += 1
            duration = row.get("duration_seconds")
            if isinstance(duration, (int, float)):
                connected_durations.append(float(duration))
        elif status == "timeout":
            timeout += 1
        elif status == "line drop":
            line_drop += 1
    average = (
        sum(connected_durations) / len(connected_durations) if connected_durations else 0.0
    )
    rate = (connected / attempted * 100) if attempted else 0.0
    return {
        "attempted": attempted,
        "connected": connected,
        "timeout": timeout,
        "line_drop": line_drop,
        "connection_rate": rate,
        "average_duration_seconds": average,
    }


class ViPullReportClient:
    """authenticatepullreport + pullreport."""

    def __init__(self, username: str, password: str, *, pull_base: str = PULL_BASE) -> None:
        self._username = username.strip()
        self._password = password.strip()
        self._base = (pull_base or PULL_BASE).rstrip("/")

    def _post(self, path: str, body: dict, *, token: str | None = None) -> tuple[Any, int]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"{self._base}/{path.lstrip('/')}"
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECS) as client:
            response = client.post(url, json=body, headers=headers)
        try:
            payload: Any = response.json()
        except ValueError:
            payload = {"_raw_text": response.text}
        return payload, response.status_code

    def authenticate(self, dni: str) -> str:
        body, status = self._post(
            "authenticatepullreport",
            {"username": self._username, "password": self._password, "dni": dni},
        )
        token = body.get("idToken") if isinstance(body, dict) else None
        if status != 200 or not token:
            raise ViPullReportError(
                f"authenticatepullreport failed (HTTP {status})"
            )
        return str(token)

    def pull_campaign(
        self,
        token: str,
        *,
        dni: str,
        campaign_id: str,
        fromdate: str,
        todate: str,
    ) -> list[dict[str, Any]]:
        body, status = self._post(
            "pullreport",
            {
                "dni": dni,
                "fromdate": fromdate,
                "todate": todate,
                "calltype": OBD_PULL_CALLTYPE,
                "campaignid": str(campaign_id),
            },
            token=token,
        )
        if status != 200:
            raise ViPullReportError(f"pullreport failed (HTTP {status})")
        if isinstance(body, list):
            return [row for row in body if isinstance(row, dict)]
        if isinstance(body, dict) and isinstance(body.get("data"), list):
            return [row for row in body["data"] if isinstance(row, dict)]
        raise ViPullReportError("pullreport returned an unexpected body")


def campaign_dni(metadata: Mapping[str, Any], from_number: str | None) -> str:
    raw = metadata.get("bulk_from_number") or from_number or ""
    return normalize_msisdn(str(raw))


def _numeric_campaign_id(value: Any) -> str | None:
    """Pull report and campaignstatus take the numeric campaign ref, not campainKey."""
    text = str(value or "").strip()
    if text.isdigit():
        return text
    return None


def obd_campaign_ids(metadata: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []

    def add(value: Any) -> None:
        text = _numeric_campaign_id(value)
        if text and text not in ids:
            ids.append(text)

    raw = metadata.get("bulk_obd_campaign_ids")
    if isinstance(raw, list):
        for item in raw:
            add(item)
    handles = metadata.get("bulk_provider_handles")
    if isinstance(handles, dict):
        add(handles.get("campaign_ref_id"))
    add(metadata.get("bulk_provider_call_sid"))
    return ids
