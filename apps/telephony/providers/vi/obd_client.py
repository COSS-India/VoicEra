"""VI CPaaS OBD outbound API client (injected credentials)."""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

import httpx

from .auth_helpers import ViAuthError, normalize_msisdn, resolve_dni_and_flow

logger = logging.getLogger(__name__)

DEFAULT_OBD_BASE = "https://cts.myvi.in:8443/Cpaas/api/v1/obdcampaignapi"
TOKEN_TTL_SECS = 86400
TOKEN_REFRESH_MARGIN_SECS = 3600
REQUEST_TIMEOUT_SECS = 30
BULK_INGEST_CHUNK_SIZE = 500
DEFAULT_DIAL_TIMEOUT = 30
IST = ZoneInfo("Asia/Kolkata")


class ViObdError(Exception):
    """VI OBD API error."""


def _normalize_cpaas_base(base: str, default: str = DEFAULT_OBD_BASE) -> str:
    """Ensure override URLs include the /Cpaas/api/v1/ prefix."""
    value = (base or "").strip().rstrip("/") or default
    if "/Cpaas/" in value or "/cpaas/" in value.lower():
        return value
    if "/api/v1/" in value:
        return value.replace("/api/v1/", "/Cpaas/api/v1/", 1)
    return default


class ViObdClient:
    """Client for VI CPaaS OBD endpoints (credentials injected by caller)."""

    def __init__(
        self,
        username: str,
        password: str,
        *,
        obd_base: str = DEFAULT_OBD_BASE,
        dni_flows: str | list | None = None,
        dni: str = "",
        flow_id: str = "",
        dialtimeout: int = DEFAULT_DIAL_TIMEOUT,
    ) -> None:
        if not (username or "").strip() or not (password or "").strip():
            raise ViObdError("username and password are required")
        self._username = username.strip()
        self._password = password.strip()
        self._obd_base = _normalize_cpaas_base(obd_base, DEFAULT_OBD_BASE)
        if dni_flows is not None and str(dni_flows).strip() != "":
            self._dni_flows: str | list = dni_flows
        elif dni or flow_id:
            self._dni_flows = [{"dni": dni, "flow_id": flow_id}]
        else:
            self._dni_flows = []
        self._dialtimeout = dialtimeout
        self._token: Optional[str] = None
        self._token_fetched_at: float = 0.0
        self._last_request_url: Optional[str] = None

    @staticmethod
    def _token_is_fresh(token: Optional[str], fetched_at: float) -> bool:
        if not token:
            return False
        age = time.monotonic() - fetched_at
        return age < (TOKEN_TTL_SECS - TOKEN_REFRESH_MARGIN_SECS)

    @staticmethod
    def _parse_response(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"_raw_text": response.text}

    def _request(
        self,
        path: str,
        *,
        token: Optional[str] = None,
        json_body: Optional[dict] = None,
    ) -> tuple[Any, int]:
        url = f"{self._obd_base.rstrip('/')}/{path.lstrip('/')}"
        self._last_request_url = url
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        with httpx.Client(timeout=REQUEST_TIMEOUT_SECS) as client:
            response = client.post(url, json=json_body, headers=headers)
        return self._parse_response(response), response.status_code

    def get_auth_token(self, *, force_refresh: bool = False) -> tuple[str, dict]:
        """Authenticate against obdcampaignapi/AuthToken."""
        if not force_refresh and self._token_is_fresh(self._token, self._token_fetched_at):
            return self._token, {
                "idToken": self._token,
                "expiresIn": TOKEN_TTL_SECS,
                "_cached": True,
                "_request_url": f"{self._obd_base.rstrip('/')}/AuthToken",
            }

        body, status = self._request(
            "AuthToken",
            json_body={"username": self._username, "password": self._password},
        )
        body = body if isinstance(body, dict) else {"_raw": body}
        body["_request_url"] = self._last_request_url

        if status != 200:
            raise ViObdError(
                f"AuthToken failed (HTTP {status}) at {self._last_request_url}: {body}"
            )

        id_token = body.get("idToken")
        if not id_token:
            raise ViObdError(
                f"AuthToken response missing idToken at {self._last_request_url}: {body}"
            )

        self._token = str(id_token)
        self._token_fetched_at = time.monotonic()
        return self._token, body

    @staticmethod
    def _campaign_window(window_hours: float = 1.0) -> dict[str, str]:
        now = datetime.now(IST)
        end = now + timedelta(hours=window_hours)
        return {
            "fromdate": now.strftime("%Y-%m-%d"),
            "todate": now.strftime("%Y-%m-%d"),
            "fromtime": now.strftime("%H:%M:%S"),
            "totime": end.strftime("%H:%M:%S"),
        }

    def create_campaign(
        self,
        token: str,
        flow_id: str,
        *,
        name: Optional[str] = None,
        description: str = "VoicERA VI campaign",
        window_hours: float = 1.0,
        dialtimeout: Optional[int] = None,
        retryintervaltype: int = 0,
        retryintervalvalue: int = 5,
        retrycount: int = 1,
    ) -> dict:
        """Create an OBD campaign with a near-immediate IST time window."""
        if dialtimeout is None:
            dialtimeout = self._dialtimeout
        if not name:
            name = f"voicera-{datetime.now(IST).strftime('%Y%m%d-%H%M%S')}"

        window = self._campaign_window(window_hours)
        payload = {
            "flowid": flow_id,
            **window,
            "dialtimeout": dialtimeout,
            "name": name,
            "description": description,
            "retryintervaltype": retryintervaltype,
            "retryintervalvalue": retryintervalvalue,
            "retrycount": retrycount,
        }

        body, status = self._request(
            "createCampaign",
            token=token,
            json_body=payload,
        )
        body = body if isinstance(body, dict) else {"_raw": body}
        body["_request_url"] = self._last_request_url

        if status != 200:
            raise ViObdError(
                f"createCampaign failed (HTTP {status}) at {self._last_request_url}: {body}"
            )
        if body.get("status") != 1:
            raise ViObdError(
                f"createCampaign returned non-success status at {self._last_request_url}: {body}"
            )
        body["_request_payload"] = payload
        return body

    @staticmethod
    def _campain_key_from_response(create_response: dict) -> str:
        campain_key = create_response.get("campainKey") or create_response.get(
            "campaignKey"
        )
        if not campain_key:
            raise ViObdError(
                f"createCampaign response missing campainKey: {create_response}"
            )
        return str(campain_key)

    @staticmethod
    def _build_ingestion_payload(
        campaign_id: str,
        dni: Any,
        msisdn: Any,
        *,
        shape: Literal["nested", "nested_and_top_level", "flat"],
    ) -> dict:
        record = {"dni": dni, "msisdn": msisdn}
        if shape == "nested":
            return {"campaign_ID": campaign_id, "Records": [record]}
        if shape == "nested_and_top_level":
            return {
                "campaign_ID": campaign_id,
                "dni": dni,
                "msisdn": msisdn,
                "Records": [record],
            }
        return {
            "campaign_ID": campaign_id,
            "dni": dni,
            "msisdn": msisdn,
            "Records": [{}],
        }

    @staticmethod
    def _build_bulk_ingestion_payload(
        campaign_id: str,
        dni: Any,
        msisdns: list[str],
    ) -> dict:
        records = [{"dni": dni, "msisdn": ms} for ms in msisdns]
        return {"campaign_ID": campaign_id, "Records": records}

    def upload_call_list(
        self,
        token: str,
        campaign_id: str,
        dni: Any,
        msisdn: Any,
        *,
        payload_shape: Literal["nested", "nested_and_top_level", "flat"] = "nested",
    ) -> tuple[dict, int]:
        payload = self._build_ingestion_payload(
            campaign_id, dni, msisdn, shape=payload_shape
        )
        body, status = self._request(
            "staticCampaignDataIngestion",
            token=token,
            json_body=payload,
        )
        body = body if isinstance(body, dict) else {"_raw": body}
        body["_request_url"] = self._last_request_url
        body["_request_payload"] = payload
        body["_payload_shape"] = payload_shape
        return body, status

    @staticmethod
    def _ingestion_succeeded(body: dict, status: int) -> bool:
        if status != 200:
            return False
        data = body.get("data") or {}
        if data.get("status") == "success":
            return True
        rows = data.get("rowsAffected")
        return isinstance(rows, int) and rows >= 1

    def upload_call_list_with_fallback(
        self,
        token: str,
        create_response: dict,
        dni: Any,
        msisdn: Any,
    ) -> tuple[dict, str]:
        campaign_id = self._campain_key_from_response(create_response)
        shapes: list[Literal["nested", "nested_and_top_level"]] = [
            "nested",
            "nested_and_top_level",
        ]

        attempts: list[dict] = []
        for shape in shapes:
            body, status = self.upload_call_list(
                token, campaign_id, dni, msisdn, payload_shape=shape
            )
            attempt_info = {
                "payload_shape": shape,
                "campaign_ID": campaign_id,
                "http_status": status,
                "request_url": body.get("_request_url"),
            }
            attempts.append(attempt_info)

            if self._ingestion_succeeded(body, status):
                body["_successful_attempt"] = attempt_info
                body["_all_attempts"] = attempts
                return body, shape

            if status == 409:
                continue

            body["_all_attempts"] = attempts
            raise ViObdError(
                f"staticCampaignDataIngestion failed with HTTP {status} "
                f"using payload_shape={shape!r}: {body}"
            )

        raise ViObdError(
            "staticCampaignDataIngestion failed for all payload shapes. "
            f"Attempts: {attempts}"
        )

    def upload_call_list_bulk(
        self,
        token: str,
        campain_key: str,
        dni: Any,
        msisdns: list[str],
        *,
        chunk_size: int = BULK_INGEST_CHUNK_SIZE,
    ) -> dict:
        """Ingest multiple numbers into one campaign (chunked if needed)."""
        if not msisdns:
            raise ViObdError("upload_call_list_bulk requires at least one msisdn")

        normalized = [normalize_msisdn(m) for m in msisdns if str(m).strip()]
        if not normalized:
            raise ViObdError("upload_call_list_bulk: no valid msisdns after normalization")

        chunks: list[list[str]] = []
        for i in range(0, len(normalized), chunk_size):
            chunks.append(normalized[i : i + chunk_size])

        total_rows = 0
        chunk_results: list[dict] = []
        logger.info(
            "VI OBD bulk ingest start: campainKey=%s dni=%s numbers=%d chunks=%d",
            campain_key,
            dni,
            len(normalized),
            len(chunks),
        )
        for index, chunk in enumerate(chunks):
            payload = self._build_bulk_ingestion_payload(campain_key, dni, chunk)
            body, status = self._request(
                "staticCampaignDataIngestion",
                token=token,
                json_body=payload,
            )
            body = body if isinstance(body, dict) else {"_raw": body}
            body["_request_url"] = self._last_request_url
            chunk_results.append(
                {
                    "chunk_index": index,
                    "http_status": status,
                    "rows_in_chunk": len(chunk),
                }
            )

            if not self._ingestion_succeeded(body, status):
                raise ViObdError(
                    f"staticCampaignDataIngestion bulk chunk {index} failed "
                    f"(HTTP {status}): {body}"
                )

            data = body.get("data") or {}
            rows = data.get("rowsAffected")
            total_rows += int(rows) if isinstance(rows, int) else len(chunk)

        logger.info(
            "VI OBD bulk ingest complete: campainKey=%s total_msisdns=%d rowsAffected=%d",
            campain_key,
            len(normalized),
            total_rows,
        )
        return {
            "data": {"rowsAffected": total_rows, "status": "success"},
            "_chunks": chunk_results,
            "_total_msisdns": len(normalized),
        }

    def get_campaign_status(
        self,
        token: str,
        campaign_id: Any,
        *,
        id_kind: str = "campaign_Ref_ID",
    ) -> tuple[dict, int]:
        payload = {"campaign_ID": campaign_id}
        body, status = self._request(
            "campaignstatus",
            token=token,
            json_body=payload,
        )
        body = body if isinstance(body, dict) else {"_raw": body}
        body["_request_url"] = self._last_request_url
        body["_request_payload"] = payload
        body["_campaign_id_kind"] = id_kind
        return body, status

    def get_campaign_status_with_fallback(
        self,
        token: str,
        campaign_ref_id: str | int,
        campain_key: Optional[str] = None,
    ) -> tuple[dict, str]:
        ref_value: Any = campaign_ref_id
        if isinstance(campaign_ref_id, str) and campaign_ref_id.isdigit():
            ref_value = int(campaign_ref_id)

        attempts: list[dict] = []
        body, status = self.get_campaign_status(
            token, ref_value, id_kind="campaign_Ref_ID"
        )
        attempts.append({"http_status": status, "id_kind": "campaign_Ref_ID"})

        if status == 200:
            body["_all_attempts"] = attempts
            return body, "campaign_Ref_ID"

        if status in (400, 406) and campain_key:
            body, status = self.get_campaign_status(
                token, campain_key, id_kind="campainKey"
            )
            attempts.append({"http_status": status, "id_kind": "campainKey"})
            if status == 200:
                body["_all_attempts"] = attempts
                return body, "campainKey"

        body["_all_attempts"] = attempts
        raise ViObdError(
            f"campaignstatus failed (HTTP {status}) for campaign_Ref_ID={campaign_ref_id!r}"
            + ("; campainKey fallback also failed" if campain_key else "")
            + f": {body}"
        )

    def place_single_outbound_call(
        self,
        to_number: str,
        *,
        from_number: str | None = None,
        agent_id: str | None = None,
        window_hours: float = 1.0,
    ) -> dict[str, Any]:
        """Auth → resolve DNI/flow → createCampaign → ingest one MSISDN."""
        del agent_id  # reserved for logging / custom_parameters in portal flows
        try:
            dni, flow_id = resolve_dni_and_flow(self._dni_flows, from_number)
        except ViAuthError as exc:
            raise ViObdError(str(exc)) from exc
        msisdn = normalize_msisdn(to_number)
        if not msisdn:
            raise ViObdError(f"Invalid to_number for VI OBD: {to_number!r}")

        token, _ = self.get_auth_token()
        create_response = self.create_campaign(
            token,
            flow_id=flow_id,
            window_hours=window_hours,
        )
        campain_key = self._campain_key_from_response(create_response)
        campaign_ref_id = create_response.get("campaign_Ref_ID")
        self.upload_call_list_with_fallback(token, create_response, dni, msisdn)

        return {
            "status": "success",
            "message": "VI outbound queued",
            "campaign_Ref_ID": campaign_ref_id,
            "campainKey": campain_key,
            "dni": dni,
            "flow_id": flow_id,
            "msisdn": msisdn,
            "call_uuid": campaign_ref_id,
            "request_uuid": campaign_ref_id,
        }

    def place_bulk_outbound_calls(
        self,
        to_numbers: list[str],
        *,
        from_number: str | None = None,
        name: Optional[str] = None,
        description: str = "VoicERA VI campaign",
    ) -> dict[str, Any]:
        """Auth → create one campaign → bulk ingest all MSISDNs."""
        msisdns = [normalize_msisdn(n) for n in to_numbers if str(n).strip()]
        msisdns = [m for m in msisdns if m]
        if not msisdns:
            raise ViObdError("place_bulk_outbound_calls requires at least one number")

        try:
            dni, flow_id = resolve_dni_and_flow(self._dni_flows, from_number)
        except ViAuthError as exc:
            raise ViObdError(str(exc)) from exc
        window_hours = max(1.0, float(math.ceil(len(msisdns) / 50.0)))
        token, _ = self.get_auth_token()
        create_response = self.create_campaign(
            token,
            flow_id=flow_id,
            name=name,
            description=description,
            window_hours=window_hours,
        )
        campain_key = self._campain_key_from_response(create_response)
        campaign_ref_id = create_response.get("campaign_Ref_ID")
        self.upload_call_list_bulk(token, campain_key, dni, msisdns)

        return {
            "status": "success",
            "message": f"VI bulk outbound queued ({len(msisdns)} numbers)",
            "campaign_Ref_ID": campaign_ref_id,
            "campainKey": campain_key,
            "dni": dni,
            "flow_id": flow_id,
            "msisdns": msisdns,
            "window_hours": window_hours,
            "call_uuid": campaign_ref_id,
            "request_uuid": campaign_ref_id,
        }
