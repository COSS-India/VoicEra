"""Probe the model-server gateway /health for slot reachability."""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

logger = logging.getLogger(__name__)


def model_server_base_url() -> str | None:
    raw = (os.getenv("MODEL_SERVER_URL") or "").strip()
    if not raw:
        return None
    # MODEL_SERVER_URL is often .../v1 — health lives on the gateway root.
    parsed = urlparse(raw)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")] or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path or "/", "", "", ""))


def fetch_gateway_health(timeout: float = 2.0) -> dict[str, Any]:
    base = model_server_base_url()
    if not base:
        return {
            "configured": False,
            "reachable": None,
            "upstreams": {},
            "reason": "MODEL_SERVER_URL unset",
        }
    url = urljoin(base.rstrip("/") + "/", "health")
    try:
        response = httpx.get(url, timeout=timeout)
    except httpx.HTTPError as exc:
        logger.warning("Gateway health probe failed: %s", exc)
        return {
            "configured": True,
            "reachable": False,
            "upstreams": {},
            "reason": str(exc),
        }
    try:
        body = response.json()
    except ValueError:
        body = {}
    upstreams = body.get("upstreams") if isinstance(body, dict) else {}
    if not isinstance(upstreams, dict):
        upstreams = {}
    return {
        "configured": True,
        "reachable": response.status_code < 500,
        "status_code": response.status_code,
        "upstreams": upstreams,
        "reason": None if response.status_code < 500 else f"HTTP {response.status_code}",
    }


def slot_view(health: dict[str, Any], slot: str) -> dict[str, Any] | None:
    upstreams = health.get("upstreams") or {}
    entry = upstreams.get(slot)
    if not isinstance(entry, dict):
        return None
    return {
        "deployed": bool(entry.get("deployed")),
        "reachable": bool(entry.get("reachable")),
        "model": entry.get("model"),
    }
