"""Vodafone Idea telephony provider — stub application APIs + WSS serializer.

Serializers require pipecat and must be imported from
``apps.telephony.providers.vi.serializers``.
"""

from apps.telephony.providers.vi.client import ViClient, client_or_fail
from apps.telephony.providers.vi.config import ViConfig, ViNumberFlowEntry
from apps.telephony.providers.vi.schemas import ViOutboundQueued

__all__ = [
    "ViClient",
    "client_or_fail",
    "ViConfig",
    "ViNumberFlowEntry",
    "ViOutboundQueued",
]
