"""Go To Market HTTP client facade — OBD dial + stub application APIs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from apps.telephony.base import missing_credentials_result

from . import application, recording
from .auth_helpers import Go2MarketAuthError, list_service_numbers, parse_obd_profiles
from .helpers import format_serviceno_e164


class Go2MarketClient:
    """Thin client matching the Vobiz/Plivo method surface for Go To Market OBD."""

    PROVIDER_LABEL = "Go To Market"

    def __init__(
        self,
        base_url: str,
        *,
        obd_profiles: str | list,
        campaigntype: str = "4",
        retryatmpt: str = "0",
        retryduration: str = "15",
    ) -> None:
        try:
            self.obd_profiles = parse_obd_profiles(obd_profiles)
        except Go2MarketAuthError as exc:
            raise ValueError(f"{self.PROVIDER_LABEL} {exc}") from exc
        self.base_url = base_url.rstrip("/")
        self.campaigntype = campaigntype
        self.retryatmpt = retryatmpt
        self.retryduration = retryduration
        primary = self.obd_profiles[0]
        self.serviceno = primary["serviceno"]
        self.ivrtemplateid = primary["ivrtemplateid"]

    @property
    def obd_profiles_json(self) -> str:
        from .auth_helpers import serialize_obd_profiles

        return serialize_obd_profiles(self.obd_profiles)

    async def create_application(
        self, app_name: str, answer_url: str
    ) -> Dict[str, Any]:
        return await application.create_application(self, app_name, answer_url)

    async def delete_application(self, application_id: str) -> Dict[str, Any]:
        return await application.delete_application(self, application_id)

    async def update_application_name(
        self, application_id: str, app_name: str
    ) -> Dict[str, Any]:
        return await application.update_application_name(
            self, application_id, app_name
        )

    async def link_number(
        self,
        phone_number: str,
        application_id: str,
        *,
        stream_url: str = "",
    ) -> Dict[str, Any]:
        return await application.link_number(
            self,
            phone_number,
            application_id,
            stream_url=stream_url,
        )

    async def unlink_number(self, phone_number: str) -> Dict[str, Any]:
        return await application.unlink_number(self, phone_number)

    async def list_numbers(self) -> Dict[str, Any]:
        return await application.list_numbers(self)

    def default_from_number(self) -> str | None:
        if not self.serviceno:
            return None
        return format_serviceno_e164(self.serviceno)

    async def initiate_call(
        self,
        *,
        from_number: str,
        to_number: str,
        answer_url: str,
        answer_method: str = "POST",
        hangup_url: Optional[str] = None,
        hangup_method: str = "POST",
    ) -> Dict[str, Any]:
        return await application.initiate_call(
            self,
            from_number=from_number,
            to_number=to_number,
            answer_url=answer_url,
            answer_method=answer_method,
            hangup_url=hangup_url,
            hangup_method=hangup_method,
        )

    async def initiate_bulk_calls(
        self,
        *,
        from_number: str,
        to_numbers: List[str],
        name: Optional[str] = None,
        description: str = "VoicERA Go To Market campaign",
    ) -> Dict[str, Any]:
        return await application.initiate_bulk_calls(
            self,
            from_number=from_number,
            to_numbers=to_numbers,
            name=name,
            description=description,
        )

    async def start_call_recording(
        self, call_sid: str, time_limit_secs: int
    ) -> Optional[str]:
        return await recording.start_call_recording(self, call_sid, time_limit_secs)

    async def fetch_recording_metadata(
        self, recording_id: str
    ) -> Optional[dict]:
        return await recording.fetch_recording_metadata(self, recording_id)

    async def download_recording(self, recording_url: str) -> Optional[bytes]:
        return await recording.download_recording(self, recording_url)

    async def wait_and_download_recording(
        self,
        recording_id: str,
        max_attempts: int = recording.DEFAULT_POLL_ATTEMPTS,
        interval_secs: float = recording.DEFAULT_POLL_INTERVAL_SECS,
    ) -> Optional[bytes]:
        return await recording.wait_and_download_recording(
            self,
            recording_id,
            max_attempts=max_attempts,
            interval_secs=interval_secs,
        )


def client_or_fail(
    base_url: str,
    *,
    obd_profiles: str | list = "",
) -> tuple[Optional[Go2MarketClient], Optional[Dict[str, Any]]]:
    try:
        return (
            Go2MarketClient(base_url, obd_profiles=obd_profiles),
            None,
        )
    except ValueError:
        return None, missing_credentials_result(Go2MarketClient.PROVIDER_LABEL)


def all_service_numbers(client: Go2MarketClient) -> list[str]:
    return list_service_numbers(client.obd_profiles)
