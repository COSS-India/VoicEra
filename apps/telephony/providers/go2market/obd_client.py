"""Go To Market OBD outbound API client (CreateOBDCampaignPost)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

from .helpers import normalize_phoneno

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
REQUEST_TIMEOUT_SECS = 30
CREATE_CAMPAIGN_PATH = "CreateOBDCampaignPost"


class Go2MarketObdError(Exception):
    """Go To Market OBD API error."""


def _schedule_datetime() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")


def _normalize_obd_base(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/")


def _campaign_url(base_url: str) -> str:
    base = _normalize_obd_base(base_url)
    if base.lower().endswith("/createobdcampaignpost"):
        return base
    return f"{base}/{CREATE_CAMPAIGN_PATH}"


def _parse_response(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        text = (response.text or "").strip()
        return {"_raw_text": text} if text else {}


def _extract_provider_call_sid(body: Any, call_id: Optional[str]) -> Optional[str]:
    if not isinstance(body, dict):
        return call_id
    for key in (
        "callid",
        "callId",
        "call_id",
        "campaignid",
        "campaignId",
        "campaign_id",
        "requestid",
        "requestId",
        "id",
    ):
        value = body.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    data = body.get("data")
    if isinstance(data, dict):
        sid = _extract_provider_call_sid(data, call_id)
        if sid:
            return sid
    if call_id and str(call_id).strip():
        return str(call_id).strip()
    return None


class Go2MarketObdClient:
    """Client for Go To Market CreateOBDCampaignPost (credentials injected)."""

    def __init__(
        self,
        ukey: str,
        serviceno: str,
        ivrtemplateid: str,
        *,
        obd_base: str,
        campaigntype: str = "4",
        retryatmpt: str = "0",
        retryduration: str = "15",
    ) -> None:
        self._ukey = (ukey or "").strip()
        self._serviceno = (serviceno or "").strip()
        self._ivrtemplateid = (ivrtemplateid or "").strip()
        self._obd_base = obd_base
        self._campaigntype = (campaigntype or "4").strip()
        self._retryatmpt = (retryatmpt or "0").strip()
        self._retryduration = (retryduration or "15").strip()
        if not self._ukey:
            raise Go2MarketObdError("ukey is required")
        if not self._serviceno:
            raise Go2MarketObdError("serviceno is required")
        if not self._ivrtemplateid:
            raise Go2MarketObdError("ivrtemplateid is required")

    def _build_payload(
        self,
        phoneno: str,
        *,
        wss_url: str,
        call_id: Optional[str] = None,
    ) -> dict[str, Any]:
        # v2 guide: msisdnlist.WSS; legacy portals also accept Param1 WSS URL.
        entry: dict[str, str] = {
            "phoneno": phoneno,
            "WSS": wss_url,
            "Param1": wss_url,
        }
        if call_id and str(call_id).strip():
            entry["callid"] = str(call_id).strip()
        return {
            "sourcetype": "1",
            "sendnow": "0",
            "schddate": _schedule_datetime(),
            "campaigntype": self._campaigntype,
            "filetype": "2",
            "ukey": self._ukey,
            "serviceno": self._serviceno,
            "ivrtemplateid": self._ivrtemplateid,
            "retryatmpt": self._retryatmpt,
            "retryduration": self._retryduration,
            "msisdnlist": [entry],
        }

    def place_single_outbound_call(
        self,
        to_number: str,
        *,
        wss_url: str,
        call_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """POST CreateOBDCampaignPost for one callee with WSS URL in Param1."""
        phoneno = normalize_phoneno(to_number)
        if not phoneno or len(phoneno) != 10 or not phoneno.isdigit():
            raise Go2MarketObdError(
                f"Invalid to_number for Go To Market OBD: {to_number!r}"
            )
        wss = (wss_url or "").strip()
        if not wss:
            raise Go2MarketObdError("wss_url is required for outbound streaming")

        payload = self._build_payload(phoneno, wss_url=wss, call_id=call_id)
        url = _campaign_url(self._obd_base)
        logger.info(
            "Go2Market OBD dial: serviceno=%s phoneno=%s wss=%s",
            self._serviceno,
            phoneno,
            wss,
        )

        with httpx.Client(timeout=REQUEST_TIMEOUT_SECS) as client:
            response = client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        body = _parse_response(response)
        if response.status_code >= 400:
            raise Go2MarketObdError(
                f"CreateOBDCampaignPost failed (HTTP {response.status_code}) "
                f"at {url}: {body}"
            )

        provider_call_sid = _extract_provider_call_sid(body, call_id)
        return {
            "status": "success",
            "message": "Go To Market outbound queued",
            "provider_call_sid": provider_call_sid,
            "call_uuid": provider_call_sid,
            "request_uuid": provider_call_sid,
            "phoneno": phoneno,
            "serviceno": self._serviceno,
            "wss_url": wss,
            "_request_url": url,
            "_request_payload": payload,
            "_response_body": body,
        }
