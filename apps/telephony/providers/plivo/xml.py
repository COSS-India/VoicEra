"""Plivo answer-stream XML.

Hangup is configured via Call/Application ``hangup_url``, not Stream attrs.
"""

from __future__ import annotations

from typing import Any


def build_answer_stream_xml(
    websocket_url: str,
    *,
    sample_rate: int = 8000,
    **_: Any,
) -> str:
    """Build Plivo XML instructing the provider to open a bidirectional stream."""
    if sample_rate == 16000:
        content_type = "audio/x-l16;rate=16000"
    else:
        content_type = f"audio/x-mulaw;rate={sample_rate}"

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream bidirectional="true" keepCallAlive="true" contentType="{content_type}">
        {websocket_url}
    </Stream>
</Response>'''
