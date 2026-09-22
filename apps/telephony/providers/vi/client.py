"""VI HTTP client facade — OBD dial + stub application/number APIs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from apps.telephony.base import Credentials, missing_credentials_result, require_credentials

from . import application, recording
from .auth_helpers import list_dnis, parse_dni_flows


class ViClient:
    """Thin client matching the Vobiz/Plivo method surface for VI CPaaS OBD.

    Credentials, base URL, and ``dni_flows`` are injected — no org lookup.
    """

    PROVIDER_LABEL = "Vodafone Idea"

    def __init__(
        self,
        auth_id: str,
        auth_token: str,
        base_url: str,
        *,
        dni_flows: str | list = "",
    ) -> None:
        creds = require_credentials(
            auth_id, auth_token, provider_label=self.PROVIDER_LABEL
        )
        if creds is None:
            raise ValueError(
                f"{self.PROVIDER_LABEL} Auth ID and Auth Token must be provided."
            )
        try:
            self.dni_flows = parse_dni_flows(dni_flows)
        except ValueError as exc:
            raise ValueError(f"{self.PROVIDER_LABEL} {exc}") from exc
        self.credentials: Credentials = creds
        self.base_url = base_url.rstrip("/")

    # --- Application ---

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

    def default_from_number(self) -> str | None:
        """First E.164 DNI from auth ``dni_flows`` (caller-ID fallback)."""
        try:
            numbers = list_dnis(self.dni_flows)
        except Exception:
            return None
        return numbers[0] if numbers else None

    # --- Outbound call ---

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
        description: str = "VoicERA VI campaign",
    ) -> Dict[str, Any]:
        """Capability hook for campaign batch dialing (one OBD campaign)."""
        return await application.initiate_bulk_calls(
            self,
            from_number=from_number,
            to_numbers=to_numbers,
            name=name,
            description=description,
        )

    async def get_campaign_status(
        self,
        *,
        campaign_ref_id: str | int,
        campain_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await application.get_campaign_status(
            self,
            campaign_ref_id=campaign_ref_id,
            campain_key=campain_key,
        )

    # --- Recording (carrier APIs unused; Pipecat AudioBuffer only) ---

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
    auth_id: Optional[str],
    auth_token: Optional[str],
    base_url: str,
    *,
    dni_flows: str | list = "",
) -> tuple[Optional[ViClient], Optional[Dict[str, Any]]]:
    """Build a client or return a fail dict (for callers with optional creds)."""
    try:
        return (
            ViClient(
                auth_id or "",
                auth_token or "",
                base_url,
                dni_flows=dni_flows,
            ),
            None,
        )
    except ValueError:
        return None, missing_credentials_result(ViClient.PROVIDER_LABEL)
