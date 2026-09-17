"""Vodafone Idea ProviderAuth validation tests."""

from __future__ import annotations

import pytest

from app.services.provider_auth_catalog import validate_auth_payload


def test_vi_auth_accepts_number_flows() -> None:
    validated = validate_auth_payload(
        "vi",
        {
            "obd_username": "user",
            "obd_password": "secret",
            "number_flows": [
                {"phone_number": "+919876543210", "flow_id": "flow-1=="},
                {"phone_number": "9876543211", "flow_id": "flow-2=="},
            ],
        },
    )
    assert validated["obd_username"] == "user"
    assert validated["obd_password"] == "secret"
    assert len(validated["number_flows"]) == 2
    assert validated["number_flows"][0]["phone_number"] == "+919876543210"


def test_vi_auth_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="rejected auth_id"):
        validate_auth_payload(
            "vi",
            {
                "obd_username": "user",
                "obd_password": "secret",
                "auth_id": "legacy",
                "number_flows": [{"phone_number": "+919876543210", "flow_id": "f1"}],
            },
        )


def test_vi_auth_requires_number_flows() -> None:
    with pytest.raises(ValueError, match="number_flows"):
        validate_auth_payload(
            "vi",
            {
                "obd_username": "user",
                "obd_password": "secret",
                "number_flows": [],
            },
        )


def test_vi_auth_rejects_duplicate_phones() -> None:
    with pytest.raises(ValueError, match="duplicate phone"):
        validate_auth_payload(
            "vi",
            {
                "obd_username": "user",
                "obd_password": "secret",
                "number_flows": [
                    {"phone_number": "+919876543210", "flow_id": "a"},
                    {"phone_number": "9876543210", "flow_id": "b"},
                ],
            },
        )
