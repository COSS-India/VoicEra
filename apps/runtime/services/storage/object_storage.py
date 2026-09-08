"""MinIO object storage for per-call transcripts and recordings."""

from __future__ import annotations

import asyncio
import io
import os
from functools import lru_cache

from loguru import logger
from minio import Minio


def _safe_segment(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value) or "unknown"


def _env_bool(key: str, default: bool = False) -> bool:
    value = (os.getenv(key) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def object_key(org_id: str, call_id: str, filename: str) -> str:
    return f"{_safe_segment(org_id)}/{_safe_segment(call_id)}/{filename}"


def minio_uri(org_id: str, call_id: str, filename: str) -> str:
    """Return a ``minio://bucket/key`` URI for a call artifact."""
    return f"minio://{_minio_bucket()}/{object_key(org_id, call_id, filename)}"


@lru_cache
def _minio_client() -> Minio:
    return Minio(
        os.getenv("MINIO_ENDPOINT", "localhost:9000"),
        access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin123"),
        secure=_env_bool("MINIO_SECURE", False),
    )


def _minio_bucket() -> str:
    return os.getenv("MINIO_BUCKET", "voicera-calls")


def _upload_bytes_sync(
    org_id: str,
    call_id: str,
    filename: str,
    data: bytes,
    content_type: str,
) -> str:
    key = object_key(org_id, call_id, filename)
    client = _minio_client()
    client.put_object(
        _minio_bucket(),
        key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return minio_uri(org_id, call_id, filename)


async def upload_bytes(
    org_id: str,
    call_id: str,
    filename: str,
    data: bytes,
    content_type: str,
) -> str | None:
    """Upload bytes to MinIO; return ``minio://`` URI on success."""
    uri = minio_uri(org_id, call_id, filename)
    try:
        uploaded_uri = await asyncio.to_thread(
            _upload_bytes_sync,
            org_id,
            call_id,
            filename,
            data,
            content_type,
        )
        logger.info("Uploaded {} to MinIO bucket={}", uploaded_uri, _minio_bucket())
        return uploaded_uri
    except Exception:
        logger.warning(
            "Failed to upload {} to MinIO bucket={}",
            uri,
            _minio_bucket(),
            exc_info=True,
        )
        return None
