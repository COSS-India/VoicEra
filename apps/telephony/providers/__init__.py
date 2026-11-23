"""Telephony providers (Vobiz, Plivo, Vodafone Idea, Go To Market)."""

from apps.telephony.providers.go2market import Go2MarketClient
from apps.telephony.providers.plivo import PlivoClient
from apps.telephony.providers.vi import ViClient
from apps.telephony.providers.vobiz import VobizClient

__all__ = ["VobizClient", "PlivoClient", "ViClient", "Go2MarketClient"]
