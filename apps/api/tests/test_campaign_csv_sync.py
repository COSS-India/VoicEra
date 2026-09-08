"""Campaign CSV validation tests."""

from __future__ import annotations

import pytest

from app.services.campaign.source_sync import CampaignSourceSyncService


def test_validate_source_data_requires_phone_column() -> None:
    result = CampaignSourceSyncService.validate_source_data(
        ["name"], [["Alice"]]
    )
    assert not result.is_valid
    assert result.error is not None
    assert "phone_number" in result.error.message


def test_validate_source_data_requires_e164() -> None:
    result = CampaignSourceSyncService.validate_source_data(
        ["phone_number"], [["5551234"]]
    )
    assert not result.is_valid
    assert result.error is not None


def test_validate_source_data_accepts_valid_rows() -> None:
    result = CampaignSourceSyncService.validate_source_data(
        ["phone_number", "name"],
        [["+14155551234", "Alice"]],
    )
    assert result.is_valid
