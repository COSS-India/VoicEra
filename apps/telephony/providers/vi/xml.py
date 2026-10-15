"""VI answer-stream XML placeholder.

Live VI media uses DIY Streaming Object → ``wss://…/vi/stream`` directly.
This builder exists only so the registry surface matches Vobiz/Plivo.
"""

from __future__ import annotations

from typing import Any


def build_answer_stream_xml(
    websocket_url: str,
    *,
    sample_rate: int = 8000,
    **_: Any,
) -> str:
    """Return documented placeholder XML (not used on the live VI path)."""
    del sample_rate
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "  <!-- VI does not use /answer Stream XML. "
        f"Configure DIY Streaming Object to {websocket_url} -->\n"
        "</Response>\n"
    )
