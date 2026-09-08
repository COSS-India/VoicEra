"""Tests for answer-stream XML builders."""

from __future__ import annotations

import pytest

from apps.telephony import build_answer_stream_xml
from apps.telephony.providers.plivo import xml as plivo_xml
from apps.telephony.providers.vobiz import xml as vobiz_xml

WS = "wss://example.com/agent/abc"


def _expected_stream_xml(websocket_url: str, sample_rate: int) -> str:
    """Canonical Stream XML body for answer webhooks."""
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


@pytest.mark.parametrize("provider", ["vobiz", "plivo", "Vobiz", "Plivo"])
@pytest.mark.parametrize("sample_rate", [8000, 16000])
def test_xml_matches_expected_stream(provider: str, sample_rate: int):
    expected = _expected_stream_xml(WS, sample_rate)
    assert build_answer_stream_xml(provider, WS, sample_rate=sample_rate) == expected


def test_unsupported_provider():
    with pytest.raises(ValueError, match="Unsupported"):
        build_answer_stream_xml("twilio", WS)


def test_provider_modules_match_parent_dispatch():
    assert vobiz_xml.build_answer_stream_xml(WS, sample_rate=16000) == build_answer_stream_xml(
        "vobiz", WS, sample_rate=16000
    )
    assert plivo_xml.build_answer_stream_xml(WS, sample_rate=8000) == build_answer_stream_xml(
        "plivo", WS, sample_rate=8000
    )
