"""Go To Market answer-stream XML placeholder.

Live Go To Market outbound passes the agent WSS URL in OBD Param1.
This builder exists only so the registry surface matches other providers.
"""

from __future__ import annotations

from typing import Any


def build_answer_stream_xml(
    websocket_url: str,
    *,
    sample_rate: int = 8000,
    **_: Any,
) -> str:
    del sample_rate
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "  <!-- Go To Market outbound does not use /answer Stream XML. "
        f"OBD Param1 WSS URL: {websocket_url} -->\n"
        "</Response>\n"
    )
