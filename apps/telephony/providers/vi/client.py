"""VI telephony client facade."""

from __future__ import annotations

from typing import Any, Dict, Optional

from apps.telephony.base import missing_credentials_result
from apps.telephony.providers.vi.config import ViConfig
from apps.telephony.providers.vi.obd.client import ViObdClient

from . import application, recording


class ViClient:
    """Facade matching Vobiz/Plivo client method names for registry callers."""

    PROVIDER_LABEL = "Vodafone Idea"

    def __init__(self, config: ViConfig) -> None:
        if not (config.obd_username or "").strip() or not (config.obd_password or "").strip():
            raise ValueError(
                f"{self.PROVIDER_LABEL} OBD username and password must be provided."
            )
        if not config.number_flows:
            raise ValueError(
                f"{self.PROVIDER_LABEL} requires at least one phone number and flow id."
            )
        self.config = config
        self.base_url = config.base_url.rstrip("/")

    def obd_client(self) -> ViObdClient:
        return ViObdClient.from_config(self.config)

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
        self, phone_number: str, application_id: str
    ) -> Dict[str, Any]:
        return await application.link_number(self, phone_number, application_id)

    async def unlink_number(self, phone_number: str) -> Dict[str, Any]:
        return await application.unlink_number(self, phone_number)

    async def list_numbers(self) -> Dict[str, Any]:
        return await application.list_numbers(self)

    async def initiate_call(
        self,
        *,
        from_number: str,
        to_number: str,
        answer_url: str,
        answer_method: str = "POST",
        hangup_url: Optional[str] = None,
        hangup_method: str = "POST",
        flow_id: Optional[str] = None,
        fallback_phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await application.initiate_call(
            self,
            from_number=from_number,
            to_number=to_number,
            answer_url=answer_url,
            answer_method=answer_method,
            hangup_url=hangup_url,
            hangup_method=hangup_method,
            flow_id=flow_id,
            fallback_phone=fallback_phone,
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


def client_or_fail(config: ViConfig) -> tuple[Optional[ViClient], Optional[Dict[str, Any]]]:
    """Build a client or return a fail dict (for callers with optional creds)."""
    try:
        return ViClient(config), None
    except ValueError:
        return None, missing_credentials_result(ViClient.PROVIDER_LABEL)
