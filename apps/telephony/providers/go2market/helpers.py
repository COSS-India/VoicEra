"""Go To Market helpers: MSISDN, answer URL → agent WSS, query parsing."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

_PHONE_DIGITS = re.compile(r"\D+")


def normalize_phoneno(number: str) -> str:
    """Strip to 10-digit national MSISDN for OBD (e.g. +919876543210 → 9876543210)."""
    value = str(number or "").strip().lstrip("+")
    value = _PHONE_DIGITS.sub("", value)
    if value.startswith("91") and len(value) > 10:
        value = value[2:]
    return value


def format_serviceno_e164(serviceno: str) -> str:
    """Format Go To Market service number as E.164 for caller ID display."""
    digits = _PHONE_DIGITS.sub("", str(serviceno or "").strip().lstrip("+"))
    if len(digits) == 10 and digits.isdigit():
        return f"+91{digits}"
    if digits.startswith("91") and len(digits) == 12:
        return f"+{digits}"
    if digits:
        return f"+{digits}" if not str(serviceno).startswith("+") else str(serviceno).strip()
    return str(serviceno or "").strip()


def extract_query_param(answer_url: str, key: str) -> Optional[str]:
    try:
        query = parse_qs(urlparse(answer_url).query)
        values = query.get(key) or []
        if values and str(values[0]).strip():
            return str(values[0]).strip()
    except Exception:
        return None
    return None


def answer_url_to_agent_wss(answer_url: str) -> str:
    """Rewrite an HTTP answer URL into ``wss://host/agent/{org}/{agent}?call_id=…``."""
    org_id = extract_query_param(answer_url, "org_id") or ""
    agent_id = extract_query_param(answer_url, "agent_id") or ""
    call_id = extract_query_param(answer_url, "call_id") or ""

    raw = (answer_url or "").strip()
    if not raw:
        path = f"/agent/{org_id}/{agent_id}" if org_id and agent_id else "/agent"
        return path

    if raw.startswith("https://"):
        host = raw[len("https://") :]
        scheme = "wss://"
    elif raw.startswith("http://"):
        host = raw[len("http://") :]
        scheme = "ws://"
    elif raw.startswith("wss://") or raw.startswith("ws://"):
        scheme, _, rest = raw.partition("://")
        host = rest
        scheme = f"{scheme}://"
    else:
        host = raw
        scheme = "wss://"

    host_only = host.split("/")[0].split("?")[0]
    base = f"{scheme}{host_only}/agent/{org_id}/{agent_id}"
    if call_id:
        return f"{base}?call_id={call_id}"
    return base
