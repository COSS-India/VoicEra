"""Plivo HTTP client — Basic auth and base URL."""

from __future__ import annotations

from typing import Any, Dict, Optional

from apps.telephony.base import Credentials, missing_credentials_result, require_credentials

from . import application, recording


class PlivoClient:
    """Thin client for Plivo Application, outbound Call, and Recording APIs.

    Credentials and base URL are injected — no org/Integrations lookup.
    """

    PROVIDER_LABEL = "Plivo"

    def __init__(
        self,
        auth_id: str,
        auth_token: str,
        base_url: str,
    ) -> None:
        creds = require_credentials(
            auth_id, auth_token, provider_label=self.PROVIDER_LABEL
        )
        if creds is None:
            raise ValueError(
                f"{self.PROVIDER_LABEL} Auth ID and Auth Token must be provided."
            )
        self.credentials: Credentials = creds
        self.base_url = base_url.rstrip("/")

    def auth_tuple(self) -> tuple[str, str]:
        return self.credentials.auth_id, self.credentials.auth_token

    def auth_headers(self, *, include_content_type: bool = False) -> Dict[str, str]:
        headers: Dict[str, str] = {"Accept": "application/json"}
        if include_content_type:
            headers["Content-Type"] = "application/json"
        return headers

    def account_url(self, *parts: str) -> str:
        """Join path parts under ``/Account/{auth_id}/``, preserving a trailing slash."""
        segments: list[str] = []
        trailing_slash = False
        for p in parts:
            if not p:
                continue
            trailing_slash = p.endswith("/")
            segments.append(p.strip("/"))
        path = "/".join(segments)
        if trailing_slash and path:
            path += "/"
        return f"{self.base_url}/Account/{self.credentials.auth_id}/{path}"

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

    # --- Recording ---

    async def start_call_recording(
        self, call_uuid: str, time_limit_secs: int
    ) -> Optional[str]:
        return await recording.start_call_recording(self, call_uuid, time_limit_secs)

    async def fetch_recording_metadata(
        self, recording_id: str
    ) -> Optional[dict]:
        return await recording.fetch_recording_metadata(self, recording_id)

    async def list_recordings_for_call(self, call_uuid: str) -> Optional[dict]:
        return await recording.list_recordings_for_call(self, call_uuid)

    async def download_recording(self, recording_url: str) -> Optional[bytes]:
        return await recording.download_recording(self, recording_url)

    async def wait_and_download_recording(
        self,
        recording_id: Optional[str] = None,
        call_uuid: Optional[str] = None,
        max_attempts: int = recording.DEFAULT_POLL_ATTEMPTS,
        interval_secs: float = recording.DEFAULT_POLL_INTERVAL_SECS,
    ) -> Optional[bytes]:
        return await recording.wait_and_download_recording(
            self,
            recording_id=recording_id,
            call_uuid=call_uuid,
            max_attempts=max_attempts,
            interval_secs=interval_secs,
        )


def client_or_fail(
    auth_id: Optional[str],
    auth_token: Optional[str],
    base_url: str,
) -> tuple[Optional[PlivoClient], Optional[Dict[str, Any]]]:
    """Build a client or return a fail dict (for callers with optional creds)."""
    try:
        return PlivoClient(auth_id or "", auth_token or "", base_url), None
    except ValueError:
        return None, missing_credentials_result(PlivoClient.PROVIDER_LABEL)
