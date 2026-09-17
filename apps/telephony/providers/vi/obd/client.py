"""VI CPaaS OBD outbound API client (config-injected credentials)."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Optional

import httpx

from apps.telephony.providers.vi.obd.campaign import (
    create_campaign_payload,
    parse_create_campaign_response,
    status_attempt,
)
from apps.telephony.providers.vi.obd.constants import (
    BULK_INGEST_CHUNK_SIZE,
    DEFAULT_OBD_BASE,
    IST,
    REQUEST_TIMEOUT_SECS,
    TOKEN_REFRESH_MARGIN_SECS,
    TOKEN_TTL_SECS,
)
from apps.telephony.providers.vi.obd.dni import resolve_dni
from apps.telephony.providers.vi.obd.errors import ViObdError
from apps.telephony.providers.vi.obd.ingest import (
    build_bulk_ingestion_payload,
    build_ingestion_payload,
    campain_key_from_response,
    ingestion_succeeded,
)
from apps.telephony.providers.vi.obd.normalize import normalize_cpaas_base, normalize_msisdn

if TYPE_CHECKING:
    from apps.telephony.providers.vi.config import ViConfig

logger = logging.getLogger(__name__)


class ViObdClient:
    """Client for VI CPaaS OBD endpoints."""

    def __init__(
        self,
        username: str,
        password: str,
        obd_base: str = DEFAULT_OBD_BASE,
    ):
        self._username = (username or "").strip()
        self._password = (password or "").strip()
        if not self._username or not self._password:
            raise ViObdError("OBD username and password are required")
        self._obd_base = normalize_cpaas_base(obd_base, DEFAULT_OBD_BASE)
        self._token: Optional[str] = None
        self._token_fetched_at: float = 0.0
        self._last_request_url: Optional[str] = None

    @classmethod
    def from_config(cls, cfg: "ViConfig") -> "ViObdClient":
        return cls(cfg.obd_username, cfg.obd_password, cfg.base_url)

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

    def get_auth_token(
        self,
        *,
        force_refresh: bool = False,
    ) -> tuple[str, dict]:
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

        self._token = id_token
        self._token_fetched_at = time.monotonic()
        return id_token, body

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
        payload = create_campaign_payload(
            flow_id,
            name=name,
            description=description,
            window_hours=window_hours,
            dialtimeout=dialtimeout,
            retryintervaltype=retryintervaltype,
            retryintervalvalue=retryintervalvalue,
            retrycount=retrycount,
        )
        body, status = self._request(
            "createCampaign",
            token=token,
            json_body=payload,
        )
        parsed = parse_create_campaign_response(body, status, self._last_request_url)
        parsed["_request_payload"] = payload
        return parsed

    def get_active_dni(self, token: str, flow_id: str) -> dict:
        payload = {"flowId": flow_id}
        body, status = self._request(
            "getActiveDNIList",
            token=token,
            json_body=payload,
        )
        body = body if isinstance(body, dict) else {"_raw": body}
        body["_request_url"] = self._last_request_url
        body["_request_payload"] = payload

        if status != 200:
            raise ViObdError(
                f"getActiveDNIList failed (HTTP {status}) at {self._last_request_url}: {body}"
            )
        return body

    def upload_call_list(
        self,
        token: str,
        campaign_id: str,
        dni: Any,
        msisdn: Any,
        *,
        payload_shape: Literal["nested", "nested_and_top_level", "flat"] = "nested",
    ) -> tuple[dict, int]:
        payload = build_ingestion_payload(
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

    def upload_call_list_with_fallback(
        self,
        token: str,
        create_response: dict,
        dni: Any,
        msisdn: Any,
    ) -> tuple[dict, str]:
        campaign_id = campain_key_from_response(create_response)
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
                "request_payload": body.get("_request_payload"),
                "http_status": status,
                "request_url": body.get("_request_url"),
                "response": {
                    k: v
                    for k, v in body.items()
                    if k not in ("_request_payload", "_payload_shape")
                },
            }
            attempts.append(attempt_info)

            if ingestion_succeeded(body, status):
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
        for index, chunk in enumerate(chunks):
            payload = build_bulk_ingestion_payload(campain_key, dni, chunk)
            body, status = self._request(
                "staticCampaignDataIngestion",
                token=token,
                json_body=payload,
            )
            body = body if isinstance(body, dict) else {"_raw": body}
            body["_request_url"] = self._last_request_url
            body["_request_payload"] = payload
            body["_chunk_index"] = index
            body["_chunk_size"] = len(chunk)
            chunk_results.append(
                {
                    "chunk_index": index,
                    "http_status": status,
                    "rows_in_chunk": len(chunk),
                    "response": {
                        k: v
                        for k, v in body.items()
                        if not k.startswith("_") or k == "_raw_text"
                    },
                }
            )

            if not ingestion_succeeded(body, status):
                raise ViObdError(
                    f"staticCampaignDataIngestion bulk chunk {index} failed "
                    f"(HTTP {status}): {body}"
                )

            data = body.get("data") or {}
            rows = data.get("rowsAffected")
            total_rows += int(rows) if isinstance(rows, int) else len(chunk)

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
        attempts.append(status_attempt(body, status))

        if status == 200:
            body["_successful_attempt"] = attempts[-1]
            body["_all_attempts"] = attempts
            return body, "campaign_Ref_ID"

        if status in (400, 406) and campain_key:
            body, status = self.get_campaign_status(
                token, campain_key, id_kind="campainKey"
            )
            attempts.append(status_attempt(body, status))
            if status == 200:
                body["_successful_attempt"] = attempts[-1]
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
        msisdn: str,
        *,
        agent_id: str,
        flow_id: str,
        fallback_phone: str,
        name: Optional[str] = None,
        window_hours: float = 1.0,
    ) -> dict:
        """Auth → resolve DNI → createCampaign → ingest one number."""
        flow = (flow_id or "").strip()
        if not flow:
            raise ViObdError("flow_id is required for VI outbound dial")

        token, _auth = self.get_auth_token()
        dni, dni_source, dni_list = resolve_dni(
            self, token, flow, fallback_phone=fallback_phone
        )
        msisdn_norm = normalize_msisdn(msisdn)
        if not msisdn_norm:
            raise ViObdError("Invalid msisdn")

        campaign_name = name or (
            f"test-{agent_id}-{datetime.now(IST).strftime('%Y%m%d-%H%M%S')}"
        )
        logger.info(
            "VI OBD place_single_outbound_call: agent=%s flow_id=%s dni=%s msisdn=%s",
            agent_id,
            flow,
            dni,
            msisdn_norm,
        )
        create_response = self.create_campaign(
            token,
            flow_id=flow,
            name=campaign_name,
            window_hours=window_hours,
        )
        ingest_response, payload_shape = self.upload_call_list_with_fallback(
            token,
            create_response,
            dni,
            msisdn_norm,
        )

        return {
            "status": "queued",
            "provider": "vi",
            "agent_id": agent_id,
            "msisdn": msisdn_norm,
            "dni": dni,
            "dni_source": dni_source,
            "dni_list": dni_list,
            "flow_id": flow,
            "campainKey": create_response.get("campainKey"),
            "campaign_Ref_ID": create_response.get("campaign_Ref_ID"),
            "payload_shape": payload_shape,
            "message": (
                "Call queued in VI OBD campaign — VI will dial within the active time window."
            ),
            "create_campaign": create_response,
            "ingest": ingest_response,
        }
