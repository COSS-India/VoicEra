"""S3-compatible object storage for call artifacts, campaign CSVs and KB files.

Works with any S3-compatible endpoint (infra S3, AWS S3, or a local MinIO
container) through boto3. Which bucket is used is purely configuration:

* dev / testing   -> ``S3_BUCKET=voicera-local-dev``
* production      -> ``S3_BUCKET=<prod bucket>``

Configuration (environment variables, first match wins; the repo-root ``.env``
is used as a fallback so local ``uvicorn`` runs pick it up like ``Settings``):

==========================  ==================================================
S3_ENDPOINT_URL             e.g. ``https://sosnm1.shakticloud.ai:9024``.
                            Falls back to ``MINIO_ENDPOINT`` + ``MINIO_SECURE``.
                            Unset (and no MinIO fallback) -> AWS default.
S3_ACCESS_KEY_ID            -> ``AWS_ACCESS_KEY_ID`` -> ``MINIO_ACCESS_KEY``.
S3_SECRET_ACCESS_KEY        -> ``AWS_SECRET_ACCESS_KEY`` -> ``MINIO_SECRET_KEY``.
S3_REGION                   -> ``AWS_DEFAULT_REGION`` -> ``us-east-1``.
S3_BUCKET                   -> ``MINIO_BUCKET`` -> ``voicera-local-dev``.
S3_ADDRESSING_STYLE         ``path`` (default, needed by most on-prem S3) or
                            ``virtual`` / ``auto``.
S3_VERIFY_SSL               ``true`` (default) / ``false``.
S3_CA_BUNDLE                Optional path to a CA bundle for a private CA.
S3_PUBLIC_ENDPOINT_URL      Optional endpoint used only to sign presigned URLs
                            handed to browsers (when the in-cluster endpoint is
                            not reachable from users' machines).
S3_LEGACY_KEY_PREFIX        Optional prefix under which pre-migration MinIO
                            objects were copied, e.g. ``voicera-calls/``.
S3_MAX_POOL_CONNECTIONS     HTTP connection pool size (default 32).
==========================  ==================================================

Artifact URIs written to the CallLog are ``s3://<bucket>/<key>``. Legacy
``minio://<bucket>/<key>`` URIs stored before the migration are still
readable: they resolve to ``S3_BUCKET`` + ``S3_LEGACY_KEY_PREFIX`` + ``<key>``.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import dotenv_values

STREAM_CHUNK_BYTES = 32 * 1024
_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}
STORAGE_URI_SCHEMES = ("s3://", "minio://")


# Same .env file Settings reads (repo root locally, "/" inside the container).
from app.config import _ENV_FILE  # noqa: E402


@lru_cache(maxsize=1)
def _dotenv() -> dict[str, str]:
    if not _ENV_FILE.is_file():
        return {}
    return {k: v for k, v in dotenv_values(_ENV_FILE).items() if v is not None}


def _lookup(key: str) -> str:
    value = os.getenv(key)
    if value is None:
        value = _dotenv().get(key)
    return (value or "").strip()


def _env(*keys: str, default: str = "") -> str:
    for key in keys:
        value = _lookup(key)
        if value:
            return value
    return default


def _env_bool(key: str, default: bool) -> bool:
    value = _lookup(key).lower()
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


@dataclass(frozen=True)
class S3Settings:
    endpoint_url: str | None
    public_endpoint_url: str | None
    access_key_id: str | None
    secret_access_key: str | None
    region: str
    bucket: str
    addressing_style: str
    verify: bool | str
    legacy_key_prefix: str
    max_pool_connections: int

    @classmethod
    def from_env(cls) -> S3Settings:
        ca_bundle = _env("S3_CA_BUNDLE")
        verify: bool | str = ca_bundle or _env_bool("S3_VERIFY_SSL", True)
        return cls(
            endpoint_url=_endpoint_url(),
            public_endpoint_url=_env("S3_PUBLIC_ENDPOINT_URL") or None,
            access_key_id=_env("S3_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID", "MINIO_ACCESS_KEY") or None,
            secret_access_key=_env(
                "S3_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY", "MINIO_SECRET_KEY"
            )
            or None,
            region=_env("S3_REGION", "AWS_DEFAULT_REGION", default="us-east-1"),
            bucket=_env("S3_BUCKET", "MINIO_BUCKET", default="voicera-local-dev"),
            addressing_style=_env("S3_ADDRESSING_STYLE", default="path"),
            verify=verify,
            legacy_key_prefix=_env("S3_LEGACY_KEY_PREFIX"),
            max_pool_connections=int(_env("S3_MAX_POOL_CONNECTIONS", default="32")),
        )


def _make_client(settings: S3Settings, endpoint_url: str | None) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        region_name=settings.region,
        verify=settings.verify,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": settings.addressing_style},
            connect_timeout=10,
            read_timeout=120,
            retries={"max_attempts": 5, "mode": "adaptive"},
            # boto3 >= 1.36 adds CRC checksums / aws-chunked uploads by default;
            # many S3-compatible stores reject them (XAmzContentSHA256Mismatch).
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            max_pool_connections=settings.max_pool_connections,
        ),
    )


def _is_not_found(exc: ClientError) -> bool:
    error = exc.response.get("Error", {}) if hasattr(exc, "response") else {}
    return str(error.get("Code", "")) in _NOT_FOUND_CODES


class ObjectStorage:
    """Thin sync + async wrapper around a boto3 S3 client."""

    def __init__(self, settings: S3Settings | None = None) -> None:
        self.settings = settings or S3Settings.from_env()
        self.client = _make_client(self.settings, self.settings.endpoint_url)
        public = self.settings.public_endpoint_url
        self._presign_client = (
            _make_client(self.settings, public) if public else self.client
        )

    @property
    def default_bucket(self) -> str:
        return self.settings.bucket

    # ------------------------------------------------------------------ URIs

    def uri(self, object_key: str, *, bucket_name: str | None = None) -> str:
        return f"s3://{bucket_name or self.default_bucket}/{object_key}"

    def parse_storage_url(self, url: str) -> tuple[str, str] | None:
        """Resolve an ``s3://`` or legacy ``minio://`` URI to ``(bucket, key)``."""
        if not url:
            return None
        if url.startswith("s3://"):
            bucket, _, key = url.removeprefix("s3://").partition("/")
            return (bucket, key) if bucket and key else None
        if url.startswith("minio://"):
            old_bucket, _, key = url.removeprefix("minio://").partition("/")
            if not old_bucket or not key:
                return None
            return self.default_bucket, f"{self.settings.legacy_key_prefix}{key}"
        return None

    @staticmethod
    def is_storage_url(url: str | None) -> bool:
        return bool(url) and str(url).startswith(STORAGE_URI_SCHEMES)

    # ------------------------------------------------------------- sync ops

    def object_exists(self, bucket_name: str, object_name: str) -> bool:
        try:
            self.client.head_object(Bucket=bucket_name, Key=object_name)
            return True
        except ClientError as exc:
            if _is_not_found(exc):
                return False
            raise

    def locate(self, object_key: str, *, bucket_name: str | None = None) -> str | None:
        """Return the key under which ``object_key`` actually exists.

        Checks the key as-is, then (if configured) under ``S3_LEGACY_KEY_PREFIX``
        for objects that were copied over from MinIO. ``None`` if absent.
        """
        bucket = bucket_name or self.default_bucket
        if self.object_exists(bucket, object_key):
            return object_key
        prefix = self.settings.legacy_key_prefix
        if prefix and not object_key.startswith(prefix):
            legacy_key = f"{prefix}{object_key}"
            if self.object_exists(bucket, legacy_key):
                return legacy_key
        return None

    def put_bytes(
        self,
        object_key: str,
        data: bytes,
        *,
        bucket_name: str | None = None,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.client.put_object(
            Bucket=bucket_name or self.default_bucket,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )

    def get_bytes(self, object_key: str, *, bucket_name: str | None = None) -> bytes:
        bucket = bucket_name or self.default_bucket
        key = object_key
        if bucket_name is None:
            key = self.locate(object_key) or object_key
        response = self.client.get_object(Bucket=bucket, Key=key)
        body = response["Body"]
        try:
            return body.read()
        finally:
            body.close()

    def iter_object(
        self,
        bucket_name: str,
        object_name: str,
        chunk_size: int = STREAM_CHUNK_BYTES,
    ) -> Iterator[bytes]:
        response = self.client.get_object(Bucket=bucket_name, Key=object_name)
        body = response["Body"]
        try:
            yield from body.iter_chunks(chunk_size)
        finally:
            body.close()

    def delete(self, object_key: str, *, bucket_name: str | None = None) -> None:
        self.client.delete_object(Bucket=bucket_name or self.default_bucket, Key=object_key)

    def presigned_get_url(
        self,
        object_key: str,
        *,
        bucket_name: str | None = None,
        expiration_seconds: int = 3600,
    ) -> str:
        return self._presign_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name or self.default_bucket, "Key": object_key},
            ExpiresIn=expiration_seconds,
        )

    def presigned_put_url(
        self,
        object_key: str,
        *,
        bucket_name: str | None = None,
        expiration_seconds: int = 1800,
    ) -> str:
        return self._presign_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket_name or self.default_bucket, "Key": object_key},
            ExpiresIn=expiration_seconds,
        )

    # ------------------------------------------------------------ async ops

    async def aobject_exists(self, bucket_name: str, object_name: str) -> bool:
        return await asyncio.to_thread(self.object_exists, bucket_name, object_name)

    async def alocate(self, object_key: str, *, bucket_name: str | None = None) -> str | None:
        return await asyncio.to_thread(self.locate, object_key, bucket_name=bucket_name)

    async def get_object_bytes(self, object_key: str, bucket_name: str | None = None) -> bytes:
        return await asyncio.to_thread(self.get_bytes, object_key, bucket_name=bucket_name)

    async def put_object_bytes(
        self,
        object_key: str,
        data: bytes,
        *,
        bucket_name: str | None = None,
        content_type: str = "application/octet-stream",
    ) -> None:
        await asyncio.to_thread(
            self.put_bytes,
            object_key,
            data,
            bucket_name=bucket_name,
            content_type=content_type,
        )


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    """Process-wide storage client (boto3 clients are thread-safe)."""
    return ObjectStorage()