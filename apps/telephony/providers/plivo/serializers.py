"""Plivo WebSocket frame serializer (requires pipecat).

Re-exports Pipecat's ``PlivoFrameSerializer`` for a symmetric API with Vobiz::

    from apps.telephony.providers.plivo.serializers import PlivoFrameSerializer
"""

from __future__ import annotations

from pipecat.serializers.plivo import PlivoFrameSerializer

__all__ = ["PlivoFrameSerializer"]
