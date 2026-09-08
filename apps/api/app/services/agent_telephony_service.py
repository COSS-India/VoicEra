"""Telephony application lifecycle for org-scoped agents.

Provider-agnostic bridge: org credentials + voice webhook URLs in, registry
clients out. Vendor-specific HTTP lives in ``apps.telephony``.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from app.config import settings
from app.services import auth_service
from apps.telephony.registry import build_config, create_client, registered_providers

logger = logging.getLogger(__name__)


class AgentTelephonyError(Exception):
    """Raised when telephony provisioning or teardown fails."""

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def supported_providers() -> frozenset[str]:
    """Telephony provider ids registered in ``apps.telephony``."""
    return registered_providers()


def _require_provider(provider: str) -> str:
    normalized = (provider or "").strip().lower()
    if normalized not in supported_providers():
        raise AgentTelephonyError(f"Unsupported telephony provider: {provider}")
    return normalized


def _require_voice_server_base_url() -> str:
    base = (settings.VOICE_SERVER_BASE_URL or "").strip().rstrip("/")
    if not base:
        raise AgentTelephonyError(
            "VOICE_SERVER_BASE_URL is not configured; required for telephony agents"
        )
    return base


def build_answer_urls(
    org_id: str,
    agent_id: str,
    call_id: str | None = None,
) -> tuple[str, str]:
    """Build answer and hangup webhook URLs for an org-scoped agent.

    Both use the same ``/answer`` endpoint; the voice server dispatches by
    ``org_id`` and ``agent_id``. When ``call_id`` is set (outbound), it is
    included for runtime correlation with CallLogs.
    """
    base = _require_voice_server_base_url()
    params: dict[str, str] = {"agent_id": agent_id, "org_id": org_id}
    if call_id:
        params["call_id"] = call_id
    query = urlencode(params)
    answer_url = f"{base}/answer?{query}"
    return answer_url, answer_url


def get_provider_dial_credentials(org_id: str, provider: str) -> dict[str, str]:
    """Return auth credentials and base URL for outbound dialing."""
    config = _build_config(org_id, provider)
    return {
        "auth_id": str(config.auth_id),
        "auth_token": str(config.auth_token),
        "base_url": str(config.base_url),
    }


def _build_config(org_id: str, provider: str):
    provider = _require_provider(provider)

    stored = auth_service.get_provider_auth(org_id, provider, mask_secrets=False)
    if not stored or not stored.get("auth"):
        raise AgentTelephonyError(
            f"Telephony credentials for provider '{provider}' are not configured "
            f"for this organisation. Configure them via POST /auth."
        )

    auth = stored["auth"]
    auth_id = str(auth.get("auth_id") or "").strip()
    auth_token = str(auth.get("auth_token") or "").strip()
    if not auth_id or not auth_token:
        raise AgentTelephonyError(
            f"Incomplete telephony credentials for provider '{provider}' "
            f"(auth_id and auth_token required)."
        )

    try:
        # Config defaults (e.g. base_url) come from the registered provider model.
        return build_config(provider, auth_id=auth_id, auth_token=auth_token)
    except (ValueError, TypeError) as exc:
        raise AgentTelephonyError(str(exc)) from exc


def load_telephony_client(org_id: str, provider: str):
    """Return a configured telephony client for ``provider``."""
    config = _build_config(org_id, provider)
    return create_client(config)


def _attachment_from_result(
    provider: str,
    org_id: str,
    agent_id: str,
    application_id: str,
) -> dict[str, Any]:
    answer_url, hangup_url = build_answer_urls(org_id, agent_id)
    return {
        "provider": provider,
        "application_id": application_id,
        "answer_url": answer_url,
        "hangup_url": hangup_url,
    }


def _raise_on_fail(result: dict[str, Any], action: str) -> None:
    if result.get("status") == "success":
        return
    message = str(result.get("message") or f"Telephony {action} failed")
    raise AgentTelephonyError(message, status_code=502)


async def provision_application(
    org_id: str,
    provider: str,
    agent_id: str,
) -> dict[str, Any]:
    """Create a provider application named by ``agent_id`` and return the attachment.

    Using the stable UUID ``agent_id`` as ``app_name`` keeps names valid for
    typical Letters/Numbers/-/_ provider rules (spaces are often rejected).
    """
    provider = _require_provider(provider)
    answer_url, _hangup_url = build_answer_urls(org_id, agent_id)
    client = load_telephony_client(org_id, provider)
    result = await client.create_application(agent_id, answer_url)
    _raise_on_fail(result, "application creation")
    application_id = result.get("app_id")
    if not application_id:
        raise AgentTelephonyError(
            "Telephony provider did not return an application id",
            status_code=502,
        )
    return _attachment_from_result(provider, org_id, agent_id, str(application_id))


async def delete_application(org_id: str, attachment: dict[str, Any]) -> None:
    """Best-effort delete of a provider application."""
    provider = str(attachment.get("provider") or "").strip()
    application_id = str(attachment.get("application_id") or "").strip()
    if not provider or not application_id:
        return
    try:
        client = load_telephony_client(org_id, provider)
        result = await client.delete_application(application_id)
        if result.get("status") != "success":
            logger.warning(
                "Failed to delete telephony application org=%s provider=%s app_id=%s: %s",
                org_id,
                provider,
                application_id,
                result.get("message"),
            )
    except AgentTelephonyError as exc:
        logger.warning(
            "Skipping telephony application delete org=%s provider=%s app_id=%s: %s",
            org_id,
            provider,
            application_id,
            exc.message,
        )
    except Exception:
        logger.exception(
            "Unexpected error deleting telephony application org=%s provider=%s app_id=%s",
            org_id,
            provider,
            application_id,
        )


async def rename_application(
    org_id: str,
    attachment: dict[str, Any],
    new_name: str,
) -> None:
    """Rename an existing provider application when the agent name changes."""
    provider = str(attachment.get("provider") or "").strip()
    application_id = str(attachment.get("application_id") or "").strip()
    if not provider or not application_id:
        return
    client = load_telephony_client(org_id, provider)
    result = await client.update_application_name(application_id, new_name)
    _raise_on_fail(result, "application rename")


async def list_provider_numbers(org_id: str, provider: str) -> list[str]:
    """List phone numbers on the org's provider account."""
    provider = _require_provider(provider)
    client = load_telephony_client(org_id, provider)
    result = await client.list_numbers()
    _raise_on_fail(result, "list numbers")
    numbers = result.get("numbers") or []
    return [str(n) for n in numbers if n]


async def link_number(
    org_id: str,
    provider: str,
    phone_number: str,
    application_id: str,
) -> None:
    """Bind a phone number to a provider application."""
    provider = _require_provider(provider)
    client = load_telephony_client(org_id, provider)
    result = await client.link_number(phone_number, application_id)
    _raise_on_fail(result, "link number")


async def unlink_number(org_id: str, provider: str, phone_number: str) -> None:
    """Unbind a phone number from its provider application."""
    provider = _require_provider(provider)
    client = load_telephony_client(org_id, provider)
    result = await client.unlink_number(phone_number)
    _raise_on_fail(result, "unlink number")
