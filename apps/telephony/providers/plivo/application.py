"""Plivo Application + outbound Call API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional
from urllib.parse import quote

from apps.telephony.base import extract_app_id, fail, request_json, success

if TYPE_CHECKING:
    from apps.telephony.providers.plivo.client import PlivoClient

logger = logging.getLogger(__name__)


async def create_application(
    client: "PlivoClient", app_name: str, answer_url: str
) -> Dict[str, Any]:
    url = client.account_url("Application/")
    payload = {
        "app_name": app_name,
        "answer_url": answer_url,
        "answer_method": "POST",
        "hangup_url": answer_url,
        "hangup_method": "POST",
    }
    data, err = await request_json(
        "POST",
        url,
        headers=client.auth_headers(include_content_type=True),
        auth=client.auth_tuple(),
        json=payload,
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        return fail(err)
    app_id = extract_app_id(data or {})
    logger.info("Plivo application created successfully for app_name=%s", app_name)
    return success("Plivo application created successfully", app_id=app_id)


async def delete_application(
    client: "PlivoClient", application_id: str
) -> Dict[str, Any]:
    url = client.account_url(f"Application/{application_id}/")
    _, err = await request_json(
        "DELETE",
        url,
        headers=client.auth_headers(),
        auth=client.auth_tuple(),
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        return fail(err)
    logger.info("Plivo application deleted successfully: %s", application_id)
    return success("Plivo application deleted successfully")


async def update_application_name(
    client: "PlivoClient", application_id: str, app_name: str
) -> Dict[str, Any]:
    """Rename a Plivo application (parity with Vobiz)."""
    url = client.account_url(f"Application/{application_id}/")
    _, err = await request_json(
        "POST",
        url,
        headers=client.auth_headers(include_content_type=True),
        auth=client.auth_tuple(),
        json={"app_name": app_name},
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        return fail(err)
    logger.info(
        "Plivo application renamed successfully: %s -> %s", application_id, app_name
    )
    return success("Plivo application renamed successfully")


async def link_number(
    client: "PlivoClient", phone_number: str, application_id: str
) -> Dict[str, Any]:
    encoded = quote(phone_number.strip(), safe="")
    url = client.account_url(f"Number/{encoded}/")
    _, err = await request_json(
        "POST",
        url,
        headers=client.auth_headers(include_content_type=True),
        auth=client.auth_tuple(),
        json={"app_id": application_id},
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        return fail(err)
    return success("Phone number linked to application successfully")


async def unlink_number(client: "PlivoClient", phone_number: str) -> Dict[str, Any]:
    encoded = quote(phone_number.strip(), safe="")
    url = client.account_url(f"Number/{encoded}/")
    _, err = await request_json(
        "POST",
        url,
        headers=client.auth_headers(include_content_type=True),
        auth=client.auth_tuple(),
        json={"app_id": ""},
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        return fail(err)
    return success("Phone number unlinked from application successfully")


async def list_numbers(client: "PlivoClient") -> Dict[str, Any]:
    url = client.account_url("Number/")
    data, err = await request_json(
        "GET",
        url,
        headers=client.auth_headers(),
        auth=client.auth_tuple(),
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        return fail(err, numbers=[])
    objects = (data or {}).get("objects", [])
    e164_numbers = [item.get("number") for item in objects if item.get("number")]
    return success(numbers=e164_numbers)


async def initiate_call(
    client: "PlivoClient",
    *,
    from_number: str,
    to_number: str,
    answer_url: str,
    answer_method: str = "POST",
    hangup_url: Optional[str] = None,
    hangup_method: str = "POST",
) -> Dict[str, Any]:
    """Start an outbound call via ``POST .../Account/{auth}/Call/``.

    Payload includes answer URL/method and optional hangup URL/method.
    """
    url = client.account_url("Call/")
    payload: Dict[str, Any] = {
        "from": from_number,
        "to": to_number,
        "answer_url": answer_url,
        "answer_method": answer_method,
    }
    if hangup_url:
        payload["hangup_url"] = hangup_url
        payload["hangup_method"] = hangup_method

    data, err = await request_json(
        "POST",
        url,
        headers=client.auth_headers(include_content_type=True),
        auth=client.auth_tuple(),
        json=payload,
        provider_label=client.PROVIDER_LABEL,
    )
    if err:
        return fail(err)

    body = data or {}
    call_uuid = (
        body.get("request_uuid")
        or body.get("call_uuid")
        or body.get("uuid")
    )
    logger.info(
        "Plivo outbound call initiated: %s → %s request_uuid=%s",
        from_number,
        to_number,
        call_uuid,
    )
    return success(
        "Call initiated successfully",
        call_uuid=call_uuid,
        request_uuid=body.get("request_uuid"),
        raw=body,
    )
