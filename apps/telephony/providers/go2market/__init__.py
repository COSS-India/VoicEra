"""Go To Market telephony provider — OBD outbound, Twilio-style streaming.

Serializers require pipecat and must be imported from
``apps.telephony.providers.go2market.serializers``.
"""

from apps.telephony.providers.go2market.client import Go2MarketClient, client_or_fail
from apps.telephony.providers.go2market.config import Go2MarketConfig
from apps.telephony.providers.go2market.schemas import Go2MarketOutboundQueued

__all__ = [
    "Go2MarketClient",
    "client_or_fail",
    "Go2MarketConfig",
    "Go2MarketOutboundQueued",
]
