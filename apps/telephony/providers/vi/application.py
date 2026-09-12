"""VI application stubs and OBD dial entrypoints.

VI does not provision provider-side applications or answer XML; the DIY flow
is configured once in the CPaaS portal. Application methods are local stubs
so agent provisioning and number attach can succeed without ProviderAuth.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from apps.telephony.base import fail, success
from apps.telephony.providers.vi.obd_client import ViObdClient, ViObdError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from apps.telephony.providers.vi.client import ViClient

VI_STUB_APP_ID = "vi-env"


async def create_application(
    client: "ViClient", app_name: str, answer_url: str
) -> Dict[str, Any]:
    del client, app_name, answer_url
    return success(
        "VI uses a portal DIY flow; no provider application created",
        app_id=VI_STUB_APP_ID,
    )


async def delete_application(
    client: "ViClient", application_id: str
) -> Dict[str, Any]:
    del client, application_id
    return success("VI stub application deleted (no-op)")


async def update_application_name(
    client: "ViClient", application_id: str, app_name: str
) -> Dict[str, Any]:
    del client, application_id, app_name
    return success("VI stub application rename (no-op)")


async def link_number(
    client: "ViClient", phone_number: str, application_id: str
) -> Dict[str, Any]:
    del client, application_id
    return success(
        "VI DNI linked locally only (portal routing uses Numbers inventory)",
        phone_number=phone_number,
    )


async def unlink_number(client: "ViClient", phone_number: str) -> Dict[str, Any]:
    del client
    return success(
        "VI DNI unlinked locally only (no-op on provider)",
        phone_number=phone_number,
    )


async def list_numbers(client: "ViClient") -> Dict[str, Any]:
    """Return the DNI from ``VI_DNI`` (VI has no provider number inventory API)."""
    del client
    import os

    dni = (os.environ.get("VI_DNI") or "").strip()
    if not dni:
        return success(
            "VI_DNI is not set in the server environment",
            numbers=[],
        )

    # Present a single E.164-style value for Numbers attach UX.
    digits = dni.lstrip("+")
    if digits.startswith("91") and len(digits) == 12 and digits.isdigit():
        display = f"+{digits}"
    elif len(digits) == 10 and digits.isdigit():
        display = f"+91{digits}"
    elif dni.startswith("+"):
        display = dni
    elif digits.isdigit():
        display = f"+{digits}"
    else:
        display = dni

    return success(
        "VI DNI from VI_DNI environment variable",
        numbers=[display],
    )


def _agent_id_from_answer_url(answer_url: str) -> str:
    try:
        query = parse_qs(urlparse(answer_url).query)
        values = query.get("agent_id") or []
        if values and str(values[0]).strip():
            return str(values[0]).strip()
    except Exception:
        pass
    return "unknown"


async def initiate_call(
    client: "ViClient",
    *,
    from_number: str,
    to_number: str,
    answer_url: str,
    answer_method: str = "POST",
    hangup_url: Optional[str] = None,
    hangup_method: str = "POST",
) -> Dict[str, Any]:
    """Queue a single outbound via VI OBD (1-row campaign)."""
    del client, from_number, answer_method, hangup_url, hangup_method
    agent_id = _agent_id_from_answer_url(answer_url)
    logger.info(
        "VI application.initiate_call: agent=%s to_number=%s",
        agent_id,
        to_number,
    )

    def _run() -> dict:
        obd = ViObdClient.from_env()
        return obd.place_single_outbound_call(to_number, agent_id=agent_id)

    try:
        result = await asyncio.to_thread(_run)
    except ViObdError as exc:
        logger.error(
            "VI application.initiate_call failed: agent=%s to_number=%s error=%s",
            agent_id,
            to_number,
            exc,
        )
        return fail(str(exc))

    campaign_ref = result.get("campaign_Ref_ID")
    logger.info(
        "VI OBD call queued: agent=%s msisdn=%s campaign_Ref_ID=%s dni=%s",
        agent_id,
        result.get("msisdn") or to_number,
        campaign_ref,
        result.get("dni"),
    )
    return success(
        str(result.get("message") or "VI outbound queued"),
        call_uuid=str(campaign_ref) if campaign_ref is not None else None,
        request_uuid=str(campaign_ref) if campaign_ref is not None else None,
        campaign_Ref_ID=campaign_ref,
        campainKey=result.get("campainKey"),
        dni=result.get("dni"),
        msisdn=result.get("msisdn"),
        raw=result,
    )
