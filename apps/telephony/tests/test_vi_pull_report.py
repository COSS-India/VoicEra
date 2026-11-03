"""VI pull-report mapping and campaignstatus flattening. No network."""

from datetime import datetime

from apps.telephony.providers.vi.application import map_obd_status_body
from apps.telephony.providers.vi.pull_report import (
    map_pull_row,
    obd_campaign_ids,
    resolve_pull_window,
    summarize_rows,
)


def test_map_pull_row_connected() -> None:
    row = map_pull_row(
        {
            "CALL ID": 40199559,
            " A PARTY NO": "9823526077",
            "A PARTY DIAL START DATE": "27/10/2026",
            "A PARTY DIAL START TIME": "14:24:00",
            "A PARTY DIAL STATUS": "Connected",
            "TOTAL DURATION(In Seconds)": 63,
            "RECORD": "https://cts.myvi.in/recording",
            "CALLER CIRCLE": "MAHARASHTRA AND GOA",
            "CALLER OPERATOR": "Vodafone - Mobile",
            "CAMPAIGN ID": 761022,
            "CAMPAIGN NAME": "campaign-c656eb54-7a418925",
        }
    )
    assert row["provider_call_id"] == "40199559"
    assert row["phone"] == "9823526077"
    assert row["when"] == "27/10/2026 14:24:00"
    assert row["duration_seconds"] == 63
    assert row["recording_url"] == "https://cts.myvi.in/recording"
    assert row["campaign_id"] == "761022"


def test_map_pull_row_no_voice() -> None:
    row = map_pull_row(
        {
            "A PARTY NO": "9999999999",
            "A PARTY DIAL STATUS": "Timeout",
            "RECORD": "No Voice",
            "TOTAL DURATION(In Seconds)": None,
        }
    )
    assert row["phone"] == "9999999999"
    assert row["recording_url"] is None
    assert row["duration_seconds"] is None


def test_summarize_rows() -> None:
    summary = summarize_rows(
        [
            {"dial_status": "Connected", "duration_seconds": 60},
            {"dial_status": "Connected", "duration_seconds": 30},
            {"dial_status": "Timeout", "duration_seconds": None},
            {"dial_status": "Line Drop", "duration_seconds": None},
        ]
    )
    assert summary["attempted"] == 4
    assert summary["connected"] == 2
    assert summary["timeout"] == 1
    assert summary["line_drop"] == 1
    assert summary["connection_rate"] == 50.0
    assert summary["average_duration_seconds"] == 45.0


def test_resolve_pull_window_converts_iso_dates() -> None:
    start, end = resolve_pull_window(
        "2026-10-26",
        "2026-10-27",
        None,
        now=datetime(2026, 10, 27, 12, 0),
    )
    assert start == "26/10/2026"
    assert end == "27/10/2026"


def test_resolve_pull_window_uses_start_through_today() -> None:
    start, end = resolve_pull_window(
        None,
        None,
        "2026-10-15T04:30:00+00:00",
        now=datetime(2026, 10, 27, 15, 0),
    )
    assert start == "15/10/2026"
    assert end == "27/10/2026"


def test_obd_campaign_ids_uses_numeric_ref_not_campain_key() -> None:
    ids = obd_campaign_ids(
        {
            "bulk_obd_campaign_ids": ["Fga9WKYZFIiTdBavkp3MKw==", "762193"],
            "bulk_provider_handles": {
                "campain_key": "Fga9WKYZFIiTdBavkp3MKw==",
                "campaign_ref_id": 762194,
            },
            "bulk_provider_call_sid": "762194",
        }
    )
    assert ids == ["762193", "762194"]


def test_map_obd_status_body() -> None:
    mapped = map_obd_status_body(
        {
            "data": {
                "campaignName": "Oldxr",
                "campaignType": "OBD with flow, campaign with api",
                "currentStatus": "Campaign finished",
                "baseDetails": {
                    "totalBaseReceived": 1,
                    "totalCallInitiated": 0,
                    "totalCallsConnected": 0,
                    "totalCallsNotConnected": 0,
                    "remainingNumbersInQueue": 1,
                    "successRatePercentage": 0,
                },
                "retryInterval": "Minutes",
                "retryWithin": 1,
                "retryAttempts": 1,
                "campaignCreatedTime": "21-07-2026 14:19:30",
                "campaignWindow": "09:10:10 - 09:55:00",
                "campaignEndDate": "22-07-2026",
            }
        },
        campaign_id="31343",
    )
    assert mapped["campaign_id"] == "31343"
    assert mapped["current_status"] == "Campaign finished"
    assert mapped["total_base_received"] == 1
    assert mapped["remaining_in_queue"] == 1
    assert mapped["success_rate_percentage"] == 0.0
    assert mapped["window"] == "09:10:10 - 09:55:00"
    assert mapped["end_date"] == "22-07-2026"
