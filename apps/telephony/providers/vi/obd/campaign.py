"""VI OBD campaign create + status."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Optional

from apps.telephony.providers.vi.obd.constants import DEFAULT_DIAL_TIMEOUT_SECS, IST
from apps.telephony.providers.vi.obd.errors import ViObdError


def campaign_window(window_hours: float = 1.0) -> dict[str, str]:
    now = datetime.now(IST)
    end = now + timedelta(hours=window_hours)
    return {
        "fromdate": now.strftime("%Y-%m-%d"),
        "todate": now.strftime("%Y-%m-%d"),
        "fromtime": now.strftime("%H:%M:%S"),
        "totime": end.strftime("%H:%M:%S"),
    }


def create_campaign_payload(
    flow_id: str,
    *,
    name: Optional[str] = None,
    description: str = "VoicERA VI campaign",
    window_hours: float = 1.0,
    dialtimeout: Optional[int] = None,
    retryintervaltype: int = 0,
    retryintervalvalue: int = 5,
    retrycount: int = 1,
) -> dict[str, Any]:
    if dialtimeout is None:
        dialtimeout = int(os.environ.get("VI_OBD_DIAL_TIMEOUT", str(DEFAULT_DIAL_TIMEOUT_SECS)))

    if not name:
        name = f"voicera-{datetime.now(IST).strftime('%Y%m%d-%H%M%S')}"

    window = campaign_window(window_hours)
    return {
        "flowid": flow_id,
        **window,
        "dialtimeout": dialtimeout,
        "name": name,
        "description": description,
        "retryintervaltype": retryintervaltype,
        "retryintervalvalue": retryintervalvalue,
        "retrycount": retrycount,
    }


def parse_create_campaign_response(body: Any, status: int, request_url: str | None) -> dict:
    body = body if isinstance(body, dict) else {"_raw": body}
    if request_url:
        body["_request_url"] = request_url

    if status != 200:
        raise ViObdError(
            f"createCampaign failed (HTTP {status}) at {request_url}: {body}"
        )
    if body.get("status") != 1:
        raise ViObdError(
            f"createCampaign returned non-success status at {request_url}: {body}"
        )
    return body


def status_attempt(body: dict, status: int) -> dict:
    return {
        "campaign_id_kind": body.get("_campaign_id_kind"),
        "request_payload": body.get("_request_payload"),
        "http_status": status,
        "request_url": body.get("_request_url"),
        "response": {
            k: v
            for k, v in body.items()
            if not k.startswith("_") or k == "_raw_text"
        },
    }
