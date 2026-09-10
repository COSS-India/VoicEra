"""VI answer-stream XML placeholder.

VI does not use answer webhooks or Stream XML — the DIY flow opens WSS
directly to ``/vi/stream``. This builder exists only so the telephony
registry has a complete answer-XML registration for provider ``vi``.
"""

from __future__ import annotations

from typing import Any


def build_answer_stream_xml(
    websocket_url: str,
    *,
    sample_rate: int = 8000,
    **_: Any,
) -> str:
    """Return a documented placeholder (unused on the live VI call path)."""
    del sample_rate
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "  <!-- Vodafone Idea uses direct WSS to /vi/stream; XML answer is unused. -->\n"
        f"  <Comment>{websocket_url}</Comment>\n"
        "</Response>"
    )
