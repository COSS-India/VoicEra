"""VI OBD campaign data ingestion payloads."""

from __future__ import annotations

from typing import Any, Literal

from apps.telephony.providers.vi.obd.errors import ViObdError


def campain_key_from_response(create_response: dict) -> str:
    campain_key = create_response.get("campainKey") or create_response.get(
        "campaignKey"
    )
    if not campain_key:
        raise ViObdError(
            f"createCampaign response missing campainKey: {create_response}"
        )
    return str(campain_key)


def build_ingestion_payload(
    campaign_id: str,
    dni: Any,
    msisdn: Any,
    *,
    shape: Literal["nested", "nested_and_top_level", "flat"],
) -> dict:
    record = {"dni": dni, "msisdn": msisdn}
    if shape == "nested":
        return {"campaign_ID": campaign_id, "Records": [record]}
    if shape == "nested_and_top_level":
        return {
            "campaign_ID": campaign_id,
            "dni": dni,
            "msisdn": msisdn,
            "Records": [record],
        }
    return {
        "campaign_ID": campaign_id,
        "dni": dni,
        "msisdn": msisdn,
        "Records": [{}],
    }


def build_bulk_ingestion_payload(
    campaign_id: str,
    dni: Any,
    msisdns: list[str],
) -> dict:
    records = [{"dni": dni, "msisdn": ms} for ms in msisdns]
    return {"campaign_ID": campaign_id, "Records": records}


def ingestion_succeeded(body: dict, status: int) -> bool:
    if status != 200:
        return False
    data = body.get("data") or {}
    if data.get("status") == "success":
        return True
    rows = data.get("rowsAffected")
    return isinstance(rows, int) and rows >= 1
