"""Tests for the shared dial/bulk result contract helpers."""

from __future__ import annotations

from apps.telephony.results import provider_call_sid_from_result


def test_provider_call_sid_prefers_canonical_key() -> None:
    assert (
        provider_call_sid_from_result(
            {
                "provider_call_sid": "sid-1",
                "call_uuid": "legacy",
            }
        )
        == "sid-1"
    )


def test_provider_call_sid_falls_back_to_legacy_keys() -> None:
    assert provider_call_sid_from_result({"call_uuid": "cu"}) == "cu"
    assert provider_call_sid_from_result({"request_uuid": "ru"}) == "ru"
    assert provider_call_sid_from_result({"uuid": "u"}) == "u"


def test_provider_call_sid_reads_nested_raw() -> None:
    assert (
        provider_call_sid_from_result({"raw": {"call_uuid": "nested"}}) == "nested"
    )


def test_provider_call_sid_ignores_vendor_wire_keys() -> None:
    assert (
        provider_call_sid_from_result(
            {"campaign_Ref_ID": 42, "campainKey": "ckey"}
        )
        is None
    )
    assert provider_call_sid_from_result(None) is None
    assert provider_call_sid_from_result({}) is None
