"""Frame serializer for the browser WebSocket transport."""

from __future__ import annotations

from typing import Any

from pipecat.frames.frames import Frame
from pipecat.serializers.protobuf import ProtobufFrameSerializer

# What @pipecat-ai/websocket-transport decodes. Its deserializer has a branch
# for each of these and throws "Unknown frame kind" on anything else (checked
# against 1.7.1 and 1.7.2).
_CLIENT_KINDS = frozenset({"audio", "message"})


class BrowserProtobufFrameSerializer(ProtobufFrameSerializer):
    """Protobuf serializer narrowed to the frame kinds a browser client reads.

    Pipecat also serializes ``text``, ``transcription`` and ``interruption``,
    so without this every user utterance raises a console error in the browser
    — which Next surfaces as an error overlay in dev. Dropping them costs the
    client nothing: transcripts and interruptions both reach it over RTVI,
    which travels as ``message``.
    """

    async def serialize(self, frame: Frame) -> str | bytes | None:
        """Serialize ``frame``, or return None if the client can't decode it."""
        kind: Any = self.SERIALIZABLE_TYPES.get(type(frame))
        # A transport message frame isn't in the map — it becomes a
        # MessageFrame in the base implementation, so let it through.
        if kind is not None and kind not in _CLIENT_KINDS:
            return None
        return await super().serialize(frame)
