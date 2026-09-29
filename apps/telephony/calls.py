"""Outbound call dispatcher by provider.

Voice servers resolve Integrations + build answer/hangup URLs, then::

    from apps.telephony import initiate_outbound

    result = await initiate_outbound(
        "vobiz",
        auth_id=...,
        auth_token=...,
        base_url=...,
        from_number=...,
        to_number=...,
        answer_url=...,
    )
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from apps.telephony.registry import build_config, create_client

__all__ = ["initiate_outbound"]


async def initiate_outbound(
    provider: str,
    *,
    auth_id: str,
    auth_token: str,
    base_url: str,
    from_number: str,
    to_number: str,
    answer_url: str,
    hangup_url: Optional[str] = None,
    answer_method: str = "POST",
    hangup_method: str = "POST",
    **auth_extras: Any,
) -> Dict[str, Any]:
    """Place an outbound call on the given provider.

    Credentials and URLs are injected — no agent/Integrations lookup here.
    Extra secret fields from ProviderAuth may be passed via ``auth_extras``.
    """
    config_kwargs: Dict[str, Any] = {
        "auth_id": auth_id,
        "auth_token": auth_token,
        "base_url": base_url,
    }
    for key, value in auth_extras.items():
        if value is not None and str(value).strip() != "":
            config_kwargs[key] = value
    config = build_config(provider, **config_kwargs)
    client = create_client(config)
    return await client.initiate_call(
        from_number=from_number,
        to_number=to_number,
        answer_url=answer_url,
        answer_method=answer_method,
        hangup_url=hangup_url,
        hangup_method=hangup_method,
    )
