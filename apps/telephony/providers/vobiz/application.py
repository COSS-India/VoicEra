"""Vobiz Application + outbound Call API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from apps.telephony.base import extract_app_id, fail, request_json, success

if TYPE_CHECKING:
    from apps.telephony.providers.vobiz.client import VobizClient

logger = logging.getLogger(__name__)


async def create_application(
    client: "VobizClient", app_name: str, answer_url: str
) -> Dict[str, Any]:
    url = client.account_url("Application/")
    payload = {
        "app_name": app_name,
        "answer_url": answer_url,
        "answer_method": "POST",
    }
    data, err = await request_json(
        "POST",
        url,
        headers=client.auth_headers(),
        json=payload,
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        return fail(err)
    app_id = extract_app_id(data or {})
    logger.info("Vobiz application created successfully for app_name=%s", app_name)
    return success("Vobiz application created successfully", app_id=app_id)


async def delete_application(
    client: "VobizClient", application_id: str
) -> Dict[str, Any]:
    url = client.account_url(f"Application/{application_id}/")
    _, err = await request_json(
        "DELETE",
        url,
        headers=client.auth_headers(include_content_type=False),
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        return fail(err)
    logger.info("Vobiz application deleted successfully: %s", application_id)
    return success("Vobiz application deleted successfully")


async def update_application_name(
    client: "VobizClient", application_id: str, app_name: str
) -> Dict[str, Any]:
    url = client.account_url(f"Application/{application_id}/")
    _, err = await request_json(
        "POST",
        url,
        headers=client.auth_headers(),
        json={"app_name": app_name},
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        return fail(err)
    logger.info(
        "Vobiz application renamed successfully: %s -> %s", application_id, app_name
    )
    return success("Vobiz application renamed successfully")


async def link_number(
    client: "VobizClient", phone_number: str, application_id: str
) -> Dict[str, Any]:
    url = client.account_url_lower(f"numbers/{phone_number}/application")
    _, err = await request_json(
        "POST",
        url,
        headers=client.auth_headers(),
        json={"application_id": application_id},
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        return fail(err)
    logger.info(
        "Phone number %s linked to application %s successfully",
        phone_number,
        application_id,
    )
    return success("Phone number linked to application successfully")


async def unlink_number(client: "VobizClient", phone_number: str) -> Dict[str, Any]:
    url = client.account_url_lower(f"numbers/{phone_number}/application")
    _, err = await request_json(
        "DELETE",
        url,
        headers=client.auth_headers(include_content_type=False),
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        return fail(err)
    logger.info(
        "Phone number %s unlinked from application successfully", phone_number
    )
    return success("Phone number unlinked from application successfully")


async def list_numbers(client: "VobizClient") -> Dict[str, Any]:
    url = client.account_url_lower("numbers")
    data, err = await request_json(
        "GET",
        url,
        headers=client.auth_headers(include_content_type=False),
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        return fail(err, numbers=[])
    e164_numbers = [
        item.get("e164")
        for item in (data or {}).get("items", [])
        if item.get("e164")
    ]
    return success(numbers=e164_numbers)


async def initiate_call(
    client: "VobizClient",
    *,
    from_number: str,
    to_number: str,
    answer_url: str,
    answer_method: str = "POST",
    hangup_url: Optional[str] = None,
    hangup_method: str = "POST",
) -> Dict[str, Any]:
    """Start an outbound call via ``POST .../Account/{auth}/Call/``.

    ``hangup_url`` / ``hangup_method`` are accepted for API symmetry with Plivo
    but are not sent on the Vobiz Call payload.
    """
    del hangup_url, hangup_method  # unused for Vobiz

    url = client.account_url("Call/")
    payload = {
        "from": from_number,
        "to": to_number,
        "answer_url": answer_url,
        "answer_method": answer_method,
    }
    data, err = await request_json(
        "POST",
        url,
        headers=client.auth_headers(),
        json=payload,
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        return fail(err)

    body = data or {}
    call_uuid = body.get("call_uuid") or body.get("request_uuid") or body.get("uuid")
    logger.info(
        "Vobiz outbound call initiated: %s → %s call_uuid=%s",
        from_number,
        to_number,
        call_uuid,
    )
    return success(
        "Call initiated successfully",
        call_uuid=call_uuid,
        raw=body,
    )
