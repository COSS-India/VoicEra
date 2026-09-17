"""SSRF guard for request-supplied outbound URLs (e.g. self-hosted LLM endpoints)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from loguru import logger

# Cloud metadata endpoints that must never be reachable via a request-supplied
# base URL — see reject_metadata_endpoint().
_METADATA_HOSTS = {"metadata.google.internal"}
_METADATA_IPS = {"169.254.169.254", "fd00:ec2::254"}


def reject_metadata_endpoint(url: str) -> None:
    """Block a request-supplied base URL from reaching cloud metadata.

    An org member fully controls this value, and the server will make an
    outbound request to it carrying whatever credentials are attached — so
    without this check, someone could point it at 169.254.169.254 (AWS/GCP/
    Azure instance metadata) and potentially exfiltrate the API's own hosting
    credentials. This blocks metadata addresses specifically, not private/
    loopback ranges generally — the whole point of self-hosted is reaching an
    org's own box on localhost or an internal network, so a blanket ban would
    defeat the feature. RFC1918/loopback are logged, not rejected.

    Checks the resolved IPs, not the literal hostname string, so a decimal or
    hex encoding of a metadata IP (e.g. ``http://2852039166/`` for
    169.254.169.254) can't bypass a naive string comparison — the OS resolver
    normalizes those forms the same way it would resolve a hostname.
    """
    hostname = urlparse(url).hostname
    if not hostname:
        raise ValueError(f"Could not parse a hostname from url: {url!r}")

    if hostname.lower() in _METADATA_HOSTS:
        raise ValueError(f"url resolves to a blocked metadata host: {hostname!r}")

    try:
        resolved = {info[4][0] for info in socket.getaddrinfo(hostname, None)}
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve url host {hostname!r}: {exc}") from exc

    if resolved & _METADATA_IPS:
        raise ValueError(f"url resolves to a blocked cloud metadata address: {hostname!r}")

    for ip in resolved:
        addr = ipaddress.ip_address(ip)
        if addr.is_private or addr.is_loopback:
            logger.info(
                "ssrf_guard: url resolves to a private/loopback address (allowed) "
                "host={} ip={}",
                hostname,
                ip,
            )
