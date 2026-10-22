"""Go To Market DID ↔ WebSocket mapping API client."""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote, urlparse

import httpx

from .helpers import normalize_phoneno
from .obd_client import Go2MarketObdError

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECS = 30
DID_WEBSOCKET_PATH = "/obd/api/did-websocket"


def did_websocket_root(obd_base_url: str) -> str:
    """Map OBD campaign base URL to the DID-WebSocket API root.

    ``https://obd.voicensms.in/obd/OBDAPI/webresources``
    → ``https://obd.voicensms.in/obd/api/did-websocket``
    """
    raw = (obd_base_url or "").strip()
    if not raw:
        raise Go2MarketObdError("OBD base_url is required for DID-WebSocket API")
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if not parsed.scheme or not parsed.netloc:
        raise Go2MarketObdError(f"Invalid OBD base_url for DID-WebSocket: {obd_base_url!r}")
    return f"{parsed.scheme}://{parsed.netloc}{DID_WEBSOCKET_PATH}"


def _parse_response(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        text = (response.text or "").strip()
        return {"_raw_text": text} if text else {}


def _raise_for_status(response: httpx.Response, *, action: str) -> Any:
    body = _parse_response(response)
    if response.status_code >= 400:
        raise Go2MarketObdError(
            f"DID-WebSocket {action} failed (HTTP {response.status_code}): {body}"
        )
    return body


def _as_mapping_list(body: Any) -> list[dict[str, Any]]:
    """Normalize GET responses into a list of mapping dicts."""
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if not isinstance(body, dict):
        return []
    for key in ("data", "result", "results", "mappings", "items"):
        nested = body.get(key)
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
        if isinstance(nested, dict):
            return [nested]
    if any(k in body for k in ("id", "did", "websocketurl")):
        return [body]
    return []


def _mapping_did(entry: dict[str, Any]) -> str:
    for key in ("did", "DID", "serviceno", "serviceNo", "phone_number"):
        value = entry.get(key)
        if value is not None and str(value).strip():
            return normalize_phoneno(str(value))
    return ""


def _mapping_id(entry: dict[str, Any]) -> Optional[int | str]:
    for key in ("id", "Id", "mappingId", "mapping_id"):
        value = entry.get(key)
        if value is None or str(value).strip() == "":
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if text.isdigit():
            return int(text)
        return text
    return None


def find_mapping_for_did(body: Any, did: str) -> Optional[dict[str, Any]]:
    """Return the first mapping whose DID matches ``did`` (normalized)."""
    target = normalize_phoneno(did)
    if not target:
        return None
    for entry in _as_mapping_list(body):
        if _mapping_did(entry) == target:
            return entry
    return None


def set_did_websocket(
    obd_base_url: str,
    *,
    ukey: str,
    did: str,
    websocketurl: str,
    isactive: bool = True,
) -> Any:
    """POST /obd/api/did-websocket — bind DID to a WSS URL."""
    ukey_value = (ukey or "").strip()
    did_value = normalize_phoneno(did)
    wss = (websocketurl or "").strip()
    if not ukey_value:
        raise Go2MarketObdError("ukey is required")
    if not did_value:
        raise Go2MarketObdError("did is required")
    if not wss:
        raise Go2MarketObdError("websocketurl is required")

    url = did_websocket_root(obd_base_url)
    payload = {
        "ukey": ukey_value,
        "did": did_value,
        "websocketurl": wss,
        "isactive": bool(isactive),
    }
    logger.info(
        "Go2Market DID-WebSocket set: did=%s active=%s wss=%s",
        did_value,
        isactive,
        wss,
    )
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECS) as client:
        response = client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
    return _raise_for_status(response, action="set")


def list_did_websockets(obd_base_url: str, *, ukey: str) -> Any:
    """GET /obd/api/did-websocket/ukey/{ukey}."""
    ukey_value = (ukey or "").strip()
    if not ukey_value:
        raise Go2MarketObdError("ukey is required")
    url = f"{did_websocket_root(obd_base_url)}/ukey/{quote(ukey_value, safe='')}"
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECS) as client:
        response = client.get(url)
    return _raise_for_status(response, action="list")


def update_did_websocket(
    obd_base_url: str,
    *,
    ukey: str,
    did: str,
    websocketurl: str,
) -> Any:
    """PUT /obd/api/did-websocket/{did} — replace the WSS URL on an existing DID."""
    ukey_value = (ukey or "").strip()
    did_value = normalize_phoneno(did)
    wss = (websocketurl or "").strip()
    if not ukey_value:
        raise Go2MarketObdError("ukey is required")
    if not did_value:
        raise Go2MarketObdError("did is required")
    if not wss:
        raise Go2MarketObdError("websocketurl is required")

    url = f"{did_websocket_root(obd_base_url)}/{quote(did_value, safe='')}"
    payload = {"ukey": ukey_value, "websocketurl": wss}
    logger.info(
        "Go2Market DID-WebSocket update: did=%s wss=%s",
        did_value,
        wss,
    )
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECS) as client:
        response = client.put(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
    return _raise_for_status(response, action="update")


def set_did_websocket_active(
    obd_base_url: str,
    *,
    ukey: str,
    mapping_id: int | str,
    isactive: bool,
) -> Any:
    """PUT /obd/api/did-websocket/active."""
    ukey_value = (ukey or "").strip()
    if not ukey_value:
        raise Go2MarketObdError("ukey is required")
    if mapping_id is None or str(mapping_id).strip() == "":
        raise Go2MarketObdError("mapping id is required")

    url = f"{did_websocket_root(obd_base_url)}/active"
    payload = {
        "ukey": ukey_value,
        "id": mapping_id,
        "isactive": bool(isactive),
    }
    logger.info(
        "Go2Market DID-WebSocket active: id=%s active=%s",
        mapping_id,
        isactive,
    )
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECS) as client:
        response = client.put(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
    return _raise_for_status(response, action="active")


def _mapping_websocketurl(entry: dict[str, Any]) -> str:
    for key in ("websocketurl", "websocketUrl", "wss", "WSS"):
        value = entry.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def deactivate_did_websocket(
    obd_base_url: str,
    *,
    ukey: str,
    did: str,
) -> bool:
    """Look up DID mapping and set ``isactive=false``. Returns True if deactivated."""
    body = list_did_websockets(obd_base_url, ukey=ukey)
    entry = find_mapping_for_did(body, did)
    if not entry:
        logger.info(
            "Go2Market DID-WebSocket deactivate: no mapping for did=%s",
            normalize_phoneno(did),
        )
        return False
    mapping_id = _mapping_id(entry)
    if mapping_id is None:
        raise Go2MarketObdError(
            f"DID-WebSocket mapping for did={did!r} has no id: {entry}"
        )
    previous_wss = _mapping_websocketurl(entry)
    logger.info(
        "Go2Market DID-WebSocket deactivate: did=%s id=%s previous_wss=%s",
        normalize_phoneno(did),
        mapping_id,
        previous_wss or "(none)",
    )
    set_did_websocket_active(
        obd_base_url,
        ukey=ukey,
        mapping_id=mapping_id,
        isactive=False,
    )
    return True


def _is_did_already_exists_error(exc: Go2MarketObdError) -> bool:
    text = str(exc).lower()
    return "already exists" in text or "did already" in text


def replace_did_websocket(
    obd_base_url: str,
    *,
    ukey: str,
    did: str,
    websocketurl: str,
) -> Any:
    """Create or update the DID → WSS mapping.

    An existing DID is updated with ``PUT /did-websocket/{did}`` and marked
    active. A new DID is created with POST. Deactivate does not free a DID
    for another create (Go2Market returns ``DID already exists``).
    """
    listed = list_did_websockets(obd_base_url, ukey=ukey)
    entry = find_mapping_for_did(listed, did)
    if entry:
        body = update_did_websocket(
            obd_base_url,
            ukey=ukey,
            did=did,
            websocketurl=websocketurl,
        )
        mapping_id = _mapping_id(entry)
        if mapping_id is not None:
            set_did_websocket_active(
                obd_base_url,
                ukey=ukey,
                mapping_id=mapping_id,
                isactive=True,
            )
        return body

    try:
        return set_did_websocket(
            obd_base_url,
            ukey=ukey,
            did=did,
            websocketurl=websocketurl,
            isactive=True,
        )
    except Go2MarketObdError as exc:
        if not _is_did_already_exists_error(exc):
            raise
        logger.warning(
            "Go2Market DID-WebSocket create hit already-exists; updating did=%s",
            normalize_phoneno(did),
        )
        return update_did_websocket(
            obd_base_url,
            ukey=ukey,
            did=did,
            websocketurl=websocketurl,
        )
