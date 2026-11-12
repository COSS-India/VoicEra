"""Unit tests for Vistaar JWT helpers (no Pipecat dependency)."""

from __future__ import annotations

from apps.providers.adapters.kenpath.vistaar_jwt import (
    VISTAAR_JWT_AUD,
    VISTAAR_JWT_ISS,
    build_vistaar_payload,
    format_vistaar_jwt_sub,
)


def test_format_vistaar_jwt_sub_indian_e164() -> None:
    assert format_vistaar_jwt_sub("+919876543210") == "+91-9876543210"


def test_format_vistaar_jwt_sub_already_hyphenated() -> None:
    assert format_vistaar_jwt_sub("+91-9000000000") == "+91-9000000000"


def test_build_vistaar_payload_claims() -> None:
    payload = build_vistaar_payload(sub="+919876543210", now=1_700_000_000)
    assert payload["sub"] == "+91-9876543210"
    assert payload["iss"] == VISTAAR_JWT_ISS
    assert payload["aud"] == VISTAAR_JWT_AUD
    assert payload["iat"] == 1_700_000_000
    assert payload["exp"] == 1_700_000_000 + 3600
