"""Answer-stream XML — public dispatcher by provider.

Voice servers should import from here only::

    from apps.telephony import build_answer_stream_xml

    xml = build_answer_stream_xml("vobiz", websocket_url, sample_rate=16000)

Each provider owns its full XML format under ``providers/{vobiz,plivo}/xml.py``.
"""

from __future__ import annotations

from typing import Any

from apps.telephony.registry import get_answer_xml_builder

__all__ = ["build_answer_stream_xml"]


def build_answer_stream_xml(
    provider: str,
    websocket_url: str,
    *,
    sample_rate: int = 8000,
    **kwargs: Any,
) -> str:
    """Build provider answer XML for a WebSocket stream URL.

    Args:
        provider: Registered telephony provider id (case-insensitive).
        websocket_url: Absolute ``wss://`` URL the provider should connect to.
        sample_rate: Audio sample rate used to pick ``contentType``.
        **kwargs: Reserved for provider-specific options (currently unused).
    """
    builder = get_answer_xml_builder(provider)
    return builder(websocket_url, sample_rate=sample_rate, **kwargs)
