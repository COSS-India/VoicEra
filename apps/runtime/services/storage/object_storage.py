"""S3-compatible object storage for per-call transcripts and recordings.

Uploads go to ``s3://<S3_BUCKET>/<org_id>/<call_id>/<filename>`` and the
returned ``s3://`` URI is linked on the CallLog. The bucket is configuration
only: ``voicera-local-dev`` for dev/testing, the prod bucket in production.

Environment variables (first match wins) — keep in sync with the API's
``app/storage/object_storage.py``:

* ``S3_ENDPOINT_URL`` (fallback ``MINIO_ENDPOINT`` + ``MINIO_SECURE``)
* ``S3_ACCESS_KEY_ID`` / ``AWS_ACCESS_KEY_ID`` / ``MINIO_ACCESS_KEY``
* ``S3_SECRET_ACCESS_KEY`` / ``AWS_SECRET_ACCESS_KEY`` / ``MINIO_SECRET_KEY``
* ``S3_REGION`` / ``AWS_DEFAULT_REGION`` (default ``us-east-1``)
* ``S3_BUCKET`` / ``MINIO_BUCKET`` (default ``voicera-local-dev``)
* ``S3_ADDRESSING_STYLE`` (default ``path``), ``S3_VERIFY_SSL``, ``S3_CA_BUNDLE``
* ``S3_MAX_POOL_CONNECTIONS`` (default 32)
* ``S3_SSE`` (``AES256`` / ``aws:kms``; empty = off) and ``S3_SSE_KMS_KEY_ID``
"""

from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config
from loguru import logger


def _safe_segment(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value) or "unknown"


def _env(*keys: str, default: str = "") -> str:
    for key in keys:
        value = (os.getenv(key) or "").strip()
        if value:
            return value
    return default


def _env_bool(key: str, default: bool = False) -> bool:
    value = (os.getenv(key) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _endpoint_url() -> str | None:
    explicit = _env("S3_ENDPOINT_URL")
    if explicit:
        return explicit
    legacy = _env("MINIO_ENDPOINT")
    if legacy:
        if legacy.startswith(("http://", "https://")):
            return legacy
        scheme = "https" if _env_bool("MINIO_SECURE", False) else "http"
        return f"{scheme}://{legacy}"
    return None


_SSE_MODES = ("AES256", "aws:kms")
_SSE_OFF = {"", "off", "none", "false", "0", "no"}


def _sse_params() -> dict[str, str]:
    """Server-side encryption arguments for ``put_object`` (empty when off)."""
    raw = _env("S3_SSE")
    if raw.lower() in _SSE_OFF:
        return {}
    mode = next((m for m in _SSE_MODES if m.lower() == raw.lower()), None)
    if mode is None:
        raise ValueError(
            f"Invalid S3_SSE={raw!r}; expected one of {', '.join(_SSE_MODES)} or empty"
        )
    params = {"ServerSideEncryption": mode}
    kms_key_id = _env("S3_SSE_KMS_KEY_ID")
    if mode == "aws:kms" and kms_key_id:
        params["SSEKMSKeyId"] = kms_key_id
    return params


def _bucket() -> str:
    return _env("S3_BUCKET", "MINIO_BUCKET", default="voicera-local-dev")


def object_key(org_id: str, call_id: str, filename: str) -> str:
    return f"{_safe_segment(org_id)}/{_safe_segment(call_id)}/{filename}"


def storage_uri(org_id: str, call_id: str, filename: str) -> str:
    """Return the ``s3://bucket/key`` URI for a call artifact."""
    return f"s3://{_bucket()}/{object_key(org_id, call_id, filename)}"


@lru_cache
def _s3_client() -> Any:
    verify: bool | str = _env("S3_CA_BUNDLE") or _env_bool("S3_VERIFY_SSL", True)
    return boto3.client(
        "s3",
        endpoint_url=_endpoint_url(),
        aws_access_key_id=_env("S3_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID", "MINIO_ACCESS_KEY") or None,
        aws_secret_access_key=_env(
            "S3_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY", "MINIO_SECRET_KEY"
        )
        or None,
        region_name=_env("S3_REGION", "AWS_DEFAULT_REGION", default="us-east-1"),
        verify=verify,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": _env("S3_ADDRESSING_STYLE", default="path")},
            connect_timeout=10,
            read_timeout=120,
            retries={"max_attempts": 5, "mode": "adaptive"},
            # boto3 >= 1.36 adds CRC checksums / aws-chunked uploads by default;
            # many S3-compatible stores reject them (XAmzContentSHA256Mismatch).
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            max_pool_connections=int(_env("S3_MAX_POOL_CONNECTIONS", default="32")),
        ),
    )


def _upload_bytes_sync(
    org_id: str,
    call_id: str,
    filename: str,
    data: bytes,
    content_type: str,
) -> str:
    _s3_client().put_object(
        Bucket=_bucket(),
        Key=object_key(org_id, call_id, filename),
        Body=data,
        ContentType=content_type,
        **_sse_params(),
    )
    return storage_uri(org_id, call_id, filename)


async def upload_bytes(
    org_id: str,
    call_id: str,
    filename: str,
    data: bytes,
    content_type: str,
) -> str | None:
    """Upload bytes to object storage; return the ``s3://`` URI on success."""
    uri = storage_uri(org_id, call_id, filename)
    try:
        uploaded_uri = await asyncio.to_thread(
            _upload_bytes_sync,
            org_id,
            call_id,
            filename,
            data,
            content_type,
        )
        logger.info("Uploaded {} ({} bytes)", uploaded_uri, len(data))
        return uploaded_uri
    except Exception as exc:
        # loguru ignores ``exc_info``; ``opt(exception=...)`` prints the traceback.
        logger.opt(exception=exc).warning(
            "Failed to upload {} ({}: {})", uri, type(exc).__name__, exc
        )
        return None