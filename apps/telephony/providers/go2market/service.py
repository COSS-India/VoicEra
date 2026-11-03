"""Go To Market telephony service registrations."""

from __future__ import annotations

from typing import Any

from apps.telephony.providers.go2market.client import Go2MarketClient
from apps.telephony.providers.go2market.config import Go2MarketConfig
from apps.telephony.registry import register_answer_xml, register_client

from . import xml as xml_mod


@register_client
def create_client(cfg: Go2MarketConfig) -> Go2MarketClient:
    return Go2MarketClient(
        cfg.base_url,
        obd_profiles=cfg.obd_profiles,
        campaigntype=cfg.campaigntype,
        retryatmpt=cfg.retryatmpt,
        retryduration=cfg.retryduration,
    )


@register_answer_xml("go2market")
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
