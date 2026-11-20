"""MinIO object storage for per-call transcripts and recordings.

``MINIO_ENCRYPTION=sse-s3`` requests server-side encryption on every upload;
:func:`verify_sse_support` checks at startup that the object store applies it.
"""

from __future__ import annotations

import asyncio
import io
import os
import socket
import uuid
from functools import lru_cache

import urllib3
from loguru import logger
from minio import Minio
from minio.error import S3Error
from minio.sse import Sse, SseS3

_SSE_MODES = frozenset({"none", "sse-s3"})
_BOOLEAN_LIKE = frozenset({"1", "true", "yes", "on", "0", "false", "no", "off"})
_SSE_PROBE_ATTEMPTS = 3


def _safe_segment(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value) or "unknown"


def _env_bool(key: str, default: bool = False) -> bool:
    value = (os.getenv(key) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def sse_mode() -> str:
    """Return the ``MINIO_ENCRYPTION`` mode; raise ``ValueError`` if invalid."""
    mode = (os.getenv("MINIO_ENCRYPTION") or "none").strip().lower()
    if mode in _SSE_MODES:
        return mode
    hint = " MINIO_ENCRYPTION is not a boolean." if mode in _BOOLEAN_LIKE else ""
    raise ValueError(
        f"Invalid MINIO_ENCRYPTION={mode!r}; "
        f"expected one of {sorted(_SSE_MODES)}.{hint}"
    )


def _minio_sse() -> Sse | None:
    return SseS3() if sse_mode() == "sse-s3" else None


def object_key(org_id: str, call_id: str, filename: str) -> str:
    return f"{_safe_segment(org_id)}/{_safe_segment(call_id)}/{filename}"


def minio_uri(org_id: str, call_id: str, filename: str) -> str:
    """Return a ``minio://bucket/key`` URI for a call artifact."""
    return f"minio://{_minio_bucket()}/{object_key(org_id, call_id, filename)}"


def _minio_endpoint() -> str:
    return os.getenv("MINIO_ENDPOINT", "localhost:9000")


def _build_minio_client(http_client: urllib3.PoolManager | None = None) -> Minio:
    return Minio(
        _minio_endpoint(),
        access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin123"),
        secure=_env_bool("MINIO_SECURE", False),
        http_client=http_client,
    )


@lru_cache
def _minio_client() -> Minio:
    return _build_minio_client()


def _minio_probe_client() -> Minio:
    """Client with short timeouts and no retries, so a startup probe cannot hang."""
    return _build_minio_client(
        urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=5, read=10),
            retries=urllib3.Retry(total=0),
        )
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
        sse=_minio_sse(),
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


def verify_sse_support_sync(client: Minio) -> None:
    """Write, stat and delete a 1-byte probe object; raise if it is not encrypted."""
    bucket = _minio_bucket()
    key = f"_system/sse-probe/{socket.gethostname()}-{uuid.uuid4().hex}"
    client.put_object(bucket, key, io.BytesIO(b"\0"), length=1, sse=_minio_sse())
    stat = client.stat_object(bucket, key)
    try:
        client.remove_object(bucket, key)
    except (S3Error, urllib3.exceptions.HTTPError, OSError):
        logger.warning(
            "Could not delete SSE probe object {}/{}", bucket, key, exc_info=True
        )
    if stat.metadata.get("x-amz-server-side-encryption") != "AES256":
        raise RuntimeError(
            "MINIO_ENCRYPTION=sse-s3 but object storage stored the probe without "
            "server-side encryption."
        )


async def verify_sse_support() -> None:
    """Fail fast if ``MINIO_ENCRYPTION`` is on but storage cannot honour it."""
    if sse_mode() == "none":
        return
    for attempt in range(1, _SSE_PROBE_ATTEMPTS + 1):
        try:
            await asyncio.to_thread(verify_sse_support_sync, _minio_probe_client())
            logger.info("Object storage SSE probe passed")
            return
        except S3Error as exc:
            if exc.code == "NotImplemented":
                raise RuntimeError(
                    "MINIO_ENCRYPTION=sse-s3 but object storage has no KMS "
                    "configured. For bundled MinIO set MINIO_KMS_SECRET_KEY "
                    "(see security-hardening guide)."
                ) from exc
            raise RuntimeError(
                "MINIO_ENCRYPTION=sse-s3 but object storage rejected the "
                f"encrypted probe: {exc.code}: {exc.message}"
            ) from exc
        except (urllib3.exceptions.HTTPError, OSError) as exc:
            if attempt == _SSE_PROBE_ATTEMPTS:
                raise RuntimeError(
                    "MINIO_ENCRYPTION=sse-s3 but object storage at "
                    f"{_minio_endpoint()} is unreachable; cannot verify encryption."
                ) from exc
            delay = 2**attempt
            logger.warning(
                "SSE probe attempt {}/{} failed ({}); retrying in {}s",
                attempt,
                _SSE_PROBE_ATTEMPTS,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
