"""Stable dial/bulk/status result contract for telephony providers.

API and other callers should only read these canonical keys:

* Single dial: ``status``, ``message``, ``provider_call_sid``
* Bulk dial: ``status``, ``message``, ``provider_call_sid``, ``from_number``,
  ``provider_handles`` (opaque dict for later status polls)
* Bulk status: ``status``, ``message``, ``state``
  (``running`` / ``completed`` / ``failed`` / ``unknown``)

Vendor wire fields (e.g. VI ``campainKey``) stay inside ``providers/<name>/``.
"""

from __future__ import annotations

from typing import Any, Mapping


_LEGACY_SID_KEYS = ("call_uuid", "request_uuid", "uuid")


def provider_call_sid_from_result(result: Mapping[str, Any] | None) -> str | None:
    """Extract the canonical provider call SID from a dial/bulk result.

    Prefers ``provider_call_sid``, then legacy ``call_uuid`` / ``request_uuid`` /
    ``uuid`` on the result and nested ``raw``. Does not look for vendor-specific
    keys such as ``campaign_Ref_ID``.
    """
    if not result:
        return None

    sid = _sid_from_mapping(result)
    if sid is not None:
        return sid

    raw = result.get("raw")
    if isinstance(raw, Mapping):
        return _sid_from_mapping(raw)
    return None


def _sid_from_mapping(data: Mapping[str, Any]) -> str | None:
    value = data.get("provider_call_sid")
    if value is not None and str(value).strip():
        return str(value)

    for key in _LEGACY_SID_KEYS:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None
