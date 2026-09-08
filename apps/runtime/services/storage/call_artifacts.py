"""Upload call artifacts to MinIO and link them on the CallLog via the API."""

from __future__ import annotations

from typing import Literal

from loguru import logger

from apps.runtime.services.backend import backend_client
from apps.runtime.services.storage.object_storage import upload_bytes

ArtifactUrlField = Literal["transcript_url", "recording_url"]


async def save_and_link(
    *,
    org_id: str,
    call_id: str | None,
    filename: str,
    data: bytes,
    content_type: str,
    url_field: ArtifactUrlField,
    link_once: bool = False,
    linked: bool = False,
) -> bool:
    """Upload artifact bytes and PATCH the CallLog with a ``minio://`` URI.

    Returns whether the CallLog was linked (``link_once`` may skip repeat PATCHes).
    """
    if not call_id:
        logger.debug("Skipping {} upload — no call_id", filename)
        return linked

    uri = await upload_bytes(org_id, call_id, filename, data, content_type)
    if not uri:
        return linked

    if link_once and linked:
        return linked

    try:
        await backend_client.update_call(
            call_id,
            org_id,
            {url_field: uri},
        )
    except Exception:
        logger.warning(
            "Failed to PATCH call_id={} field={}",
            call_id,
            url_field,
            exc_info=True,
        )
        return linked

    logger.info("Linked call_id={} {}={}", call_id, url_field, uri)
    return True
