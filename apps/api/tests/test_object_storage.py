"""Unit tests for the S3 object storage layer (in-memory S3 via moto)."""

from __future__ import annotations

from urllib.parse import urlparse

import boto3
import pytest

mock_aws = pytest.importorskip("moto").mock_aws

# ruff: noqa: E402

from app.storage import object_storage
from app.storage.object_storage import ObjectStorage, S3Settings

BUCKET = "voicera-local-dev"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    for key in (
        "S3_ENDPOINT_URL",
        "S3_PUBLIC_ENDPOINT_URL",
        "S3_LEGACY_KEY_PREFIX",
        "MINIO_ENDPOINT",
        "MINIO_SECURE",
        "MINIO_BUCKET",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "S3_SSE",
        "S3_SSE_KMS_KEY_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("S3_BUCKET", BUCKET)
    monkeypatch.setattr(object_storage, "_dotenv", lambda: {})
    return monkeypatch


@pytest.fixture
def s3(env):
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def test_settings_prefer_s3_vars_over_minio(env) -> None:
    env.setenv("MINIO_ENDPOINT", "minio:9000")
    env.setenv("S3_ENDPOINT_URL", "https://s3.example.com")
    env.setenv("S3_ACCESS_KEY_ID", "s3-key")
    env.setenv("MINIO_ACCESS_KEY", "minio-key")
    settings = S3Settings.from_env()
    assert settings.endpoint_url == "https://s3.example.com"
    assert settings.access_key_id == "s3-key"
    assert settings.bucket == BUCKET
    assert settings.addressing_style == "path"


def test_settings_fall_back_to_minio_vars(env) -> None:
    env.delenv("S3_BUCKET")
    env.setenv("MINIO_ENDPOINT", "minio:9000")
    env.setenv("MINIO_SECURE", "false")
    env.setenv("MINIO_BUCKET", "voicera-calls")
    settings = S3Settings.from_env()
    assert settings.endpoint_url == "http://minio:9000"
    assert settings.bucket == "voicera-calls"


def test_default_bucket_is_local_dev(env) -> None:
    env.delenv("S3_BUCKET")
    assert S3Settings.from_env().bucket == "voicera-local-dev"


def test_parse_storage_url(s3, env) -> None:
    storage = ObjectStorage()
    assert storage.parse_storage_url("s3://voicera-prod/org/call/recording.wav") == (
        "voicera-prod",
        "org/call/recording.wav",
    )
    # Legacy MinIO URIs map onto the configured bucket.
    assert storage.parse_storage_url("minio://voicera-calls/org/call/t.txt") == (
        BUCKET,
        "org/call/t.txt",
    )
    env.setenv("S3_LEGACY_KEY_PREFIX", "voicera-calls/")
    legacy = ObjectStorage()
    assert legacy.parse_storage_url("minio://voicera-calls/org/call/t.txt") == (
        BUCKET,
        "voicera-calls/org/call/t.txt",
    )
    assert storage.parse_storage_url("https://example.com/x") is None
    assert storage.parse_storage_url("s3://bucket-only") is None
    assert storage.parse_storage_url("") is None


def test_put_get_exists_delete_roundtrip(s3) -> None:
    storage = ObjectStorage()
    storage.put_bytes("campaigns/org-1/a.csv", b"phone\n1\n", content_type="text/csv")
    assert storage.object_exists(BUCKET, "campaigns/org-1/a.csv")
    assert storage.get_bytes("campaigns/org-1/a.csv") == b"phone\n1\n"
    head = s3.head_object(Bucket=BUCKET, Key="campaigns/org-1/a.csv")
    assert head["ContentType"] == "text/csv"
    assert b"".join(storage.iter_object(BUCKET, "campaigns/org-1/a.csv", 3)) == b"phone\n1\n"
    storage.delete("campaigns/org-1/a.csv")
    assert not storage.object_exists(BUCKET, "campaigns/org-1/a.csv")


def test_locate_falls_back_to_legacy_prefix(s3, env) -> None:
    env.setenv("S3_LEGACY_KEY_PREFIX", "voicera-calls/")
    s3.put_object(Bucket=BUCKET, Key="voicera-calls/kb/org-1/doc.pdf", Body=b"%PDF")
    storage = ObjectStorage()
    assert storage.locate("kb/org-1/doc.pdf") == "voicera-calls/kb/org-1/doc.pdf"
    assert storage.get_bytes("kb/org-1/doc.pdf") == b"%PDF"
    assert storage.locate("kb/org-1/missing.pdf") is None


@pytest.mark.asyncio
async def test_async_helpers(s3) -> None:
    storage = ObjectStorage()
    await storage.put_object_bytes("x/y.txt", b"hi", content_type="text/plain")
    assert await storage.aobject_exists(BUCKET, "x/y.txt")
    assert await storage.get_object_bytes("x/y.txt") == b"hi"
    assert await storage.alocate("x/missing.txt") is None


def test_presigned_url_uses_public_endpoint(s3, env) -> None:
    env.setenv("S3_ENDPOINT_URL", "http://s3.internal.svc:9000")
    env.setenv("S3_PUBLIC_ENDPOINT_URL", "https://s3.example.com")
    storage = ObjectStorage()
    url = urlparse(storage.presigned_get_url("campaigns/org-1/a.csv", expiration_seconds=60))
    assert url.netloc == "s3.example.com"
    # Path-style addressing: bucket is the first path segment.
    assert url.path == f"/{BUCKET}/campaigns/org-1/a.csv"
    assert "X-Amz-Signature" in url.query


def test_knowledge_upload_and_delete(s3) -> None:
    from app.services import knowledge_service

    object_storage.get_object_storage.cache_clear()
    try:
        key = knowledge_service.upload_pdf_to_storage("org-1", "doc-1", "a.pdf", b"%PDF-1.7")
        assert s3.get_object(Bucket=BUCKET, Key=key)["Body"].read() == b"%PDF-1.7"
        knowledge_service._delete_storage_object(key)
        assert s3.list_objects_v2(Bucket=BUCKET).get("KeyCount") == 0
    finally:
        object_storage.get_object_storage.cache_clear()


def test_sse_off_by_default(s3) -> None:
    storage = ObjectStorage()
    assert storage.settings.sse is None
    storage.put_bytes("plain.txt", b"x")
    assert "ServerSideEncryption" not in s3.head_object(Bucket=BUCKET, Key="plain.txt")


def test_sse_aes256_applied_on_put(s3, env) -> None:
    env.setenv("S3_SSE", "aes256")  # case-insensitive
    storage = ObjectStorage()
    assert storage.settings.sse == "AES256"
    storage.put_bytes("enc.txt", b"secret", content_type="text/plain")
    head = s3.head_object(Bucket=BUCKET, Key="enc.txt")
    assert head["ServerSideEncryption"] == "AES256"


def test_sse_kms_params(env) -> None:
    env.setenv("S3_SSE", "aws:kms")
    env.setenv("S3_SSE_KMS_KEY_ID", "key-123")
    assert S3Settings.from_env().sse_put_params() == {
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": "key-123",
    }
    env.setenv("S3_SSE", "AES256")
    # The KMS key id is ignored unless the mode is aws:kms.
    assert S3Settings.from_env().sse_put_params() == {"ServerSideEncryption": "AES256"}


def test_sse_invalid_value_rejected(env) -> None:
    env.setenv("S3_SSE", "yes-please")
    with pytest.raises(ValueError, match="Invalid S3_SSE"):
        S3Settings.from_env()