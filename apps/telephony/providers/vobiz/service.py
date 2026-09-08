"""Vobiz telephony service registrations."""

from __future__ import annotations

from typing import Any

from apps.telephony.providers.vobiz.client import VobizClient
from apps.telephony.providers.vobiz.config import VobizConfig
from apps.telephony.registry import register_answer_xml, register_client

from . import xml as xml_mod


@register_client
def create_client(cfg: VobizConfig) -> VobizClient:
    return VobizClient(cfg.auth_id, cfg.auth_token, cfg.base_url)


@register_answer_xml("vobiz")
def build_answer_stream_xml(
    websocket_url: str,
    *,
    sample_rate: int = 8000,
    **kwargs: Any,
) -> str:
    return xml_mod.build_answer_stream_xml(
        websocket_url,
        sample_rate=sample_rate,
        **kwargs,
    )
