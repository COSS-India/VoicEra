"""Telephony providers (Vobiz, Plivo, Vodafone Idea)."""

from apps.telephony.providers.plivo import PlivoClient
from apps.telephony.providers.vi import ViClient
from apps.telephony.providers.vobiz import VobizClient

__all__ = ["VobizClient", "PlivoClient", "ViClient"]
