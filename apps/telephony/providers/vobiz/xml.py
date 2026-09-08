"""Vobiz answer-stream XML.

Vobiz prefers L16 at 16 kHz (μ-law is 8 kHz only per Vobiz spec).
"""

from __future__ import annotations

from typing import Any


def build_answer_stream_xml(
    websocket_url: str,
    *,
    sample_rate: int = 8000,
    **_: Any,
) -> str:
    """Build Vobiz XML instructing the provider to open a bidirectional stream."""
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
