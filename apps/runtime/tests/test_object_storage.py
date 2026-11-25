"""Object storage SSE configuration, upload and startup-probe tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import urllib3
from fastapi.testclient import TestClient
from minio.error import S3Error
from minio.sse import SseS3

from apps.runtime.services.storage import object_storage as storage

_MODULE = "apps.runtime.services.storage.object_storage"


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch(f"{_MODULE}.asyncio.sleep", new_callable=AsyncMock) as sleep:
        yield sleep


@pytest.fixture
def sse_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINIO_ENCRYPTION", "sse-s3")


def _s3_error(code: str) -> S3Error:
    return S3Error(MagicMock(), code, "boom", "/r", "req", "host")


def _probe_client(encryption: str | None = "AES256") -> MagicMock:
    client = MagicMock()
    headers = {} if encryption is None else {"x-amz-server-side-encryption": encryption}
    client.stat_object.return_value.metadata = headers
    return client


@pytest.mark.parametrize("value", [None, "", "none", "NONE", " none "])
def test_sse_disabled(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("MINIO_ENCRYPTION", raising=False)
    else:
        monkeypatch.setenv("MINIO_ENCRYPTION", value)
    assert storage._minio_sse() is None


@pytest.mark.parametrize("value", ["sse-s3", "SSE-S3"])
def test_sse_enabled(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("MINIO_ENCRYPTION", value)
    assert isinstance(storage._minio_sse(), SseS3)


@pytest.mark.parametrize("value", ["aes", "sse-kms"])
def test_sse_invalid_value(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("MINIO_ENCRYPTION", value)
    with pytest.raises(ValueError, match="expected one of") as exc:
        storage.sse_mode()
    assert "not a boolean" not in str(exc.value)


@pytest.mark.parametrize("value", ["true", "1"])
def test_sse_boolean_value_hint(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("MINIO_ENCRYPTION", value)
    with pytest.raises(ValueError, match="not a boolean"):
        storage.sse_mode()


@pytest.mark.parametrize(
    ("mode", "expected"), [("none", type(None)), ("sse-s3", SseS3)]
)
def test_upload_passes_sse(
    monkeypatch: pytest.MonkeyPatch, mode: str, expected: type
) -> None:
    monkeypatch.setenv("MINIO_ENCRYPTION", mode)
    client = MagicMock()
    with patch(f"{_MODULE}._minio_client", return_value=client):
        uri = storage._upload_bytes_sync("org", "call", "a.wav", b"x", "audio/wav")
    assert uri.endswith("/org/call/a.wav")
    assert isinstance(client.put_object.call_args.kwargs["sse"], expected)


def test_probe_client_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINIO_SECRET_KEY", "test")
    client = storage._minio_probe_client()
    pool = client._http
    assert pool.connection_pool_kw["timeout"].connect_timeout == 5
    assert pool.connection_pool_kw["timeout"].read_timeout == 10
    assert pool.connection_pool_kw["retries"].total == 0


@pytest.mark.asyncio
async def test_probe_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINIO_ENCRYPTION", raising=False)
    with patch(f"{_MODULE}._minio_probe_client") as factory:
        await storage.verify_sse_support()
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_probe_happy_path(sse_on: None) -> None:
    client = _probe_client()
    with patch(f"{_MODULE}._minio_probe_client", return_value=client):
        await storage.verify_sse_support()
    put = client.put_object.call_args
    assert put.args[1].startswith("_system/sse-probe/")
    assert isinstance(put.kwargs["sse"], SseS3)
    client.stat_object.assert_called_once()
    client.remove_object.assert_called_once_with(put.args[0], put.args[1])


@pytest.mark.asyncio
async def test_probe_no_kms_not_retried(sse_on: None) -> None:
    client = _probe_client()
    client.put_object.side_effect = _s3_error("NotImplemented")
    with (
        patch(f"{_MODULE}._minio_probe_client", return_value=client),
        pytest.raises(RuntimeError, match="MINIO_KMS_SECRET_KEY"),
    ):
        await storage.verify_sse_support()
    assert client.put_object.call_count == 1


@pytest.mark.asyncio
async def test_probe_other_s3_error_not_retried(sse_on: None) -> None:
    client = _probe_client()
    client.put_object.side_effect = _s3_error("AccessDenied")
    with (
        patch(f"{_MODULE}._minio_probe_client", return_value=client),
        pytest.raises(RuntimeError, match="AccessDenied"),
    ):
        await storage.verify_sse_support()
    assert client.put_object.call_count == 1


@pytest.mark.asyncio
async def test_probe_unreachable_retries_then_fails(
    sse_on: None, _no_sleep: AsyncMock
) -> None:
    client = _probe_client()
    client.put_object.side_effect = urllib3.exceptions.MaxRetryError(None, "/", None)
    with (
        patch(f"{_MODULE}._minio_probe_client", return_value=client),
        pytest.raises(RuntimeError, match="unreachable"),
    ):
        await storage.verify_sse_support()
    assert client.put_object.call_count == 3
    assert [c.args[0] for c in _no_sleep.await_args_list] == [2, 4]


@pytest.mark.asyncio
async def test_probe_recovers_after_connection_error(sse_on: None) -> None:
    client = _probe_client()
    client.put_object.side_effect = [ConnectionRefusedError(), None]
    with patch(f"{_MODULE}._minio_probe_client", return_value=client):
        await storage.verify_sse_support()
    assert client.put_object.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("encryption", [None, "aws:kms"])
async def test_probe_rejects_unencrypted_object(
    sse_on: None, encryption: str | None
) -> None:
    client = _probe_client(encryption)
    with (
        patch(f"{_MODULE}._minio_probe_client", return_value=client),
        pytest.raises(RuntimeError, match="without server-side encryption"),
    ):
        await storage.verify_sse_support()
    client.remove_object.assert_called_once()


@pytest.mark.asyncio
async def test_probe_cleanup_failure_is_not_fatal(sse_on: None) -> None:
    client = _probe_client()
    client.remove_object.side_effect = _s3_error("AccessDenied")
    with (
        patch(f"{_MODULE}._minio_probe_client", return_value=client),
        patch(f"{_MODULE}.logger") as logger,
    ):
        await storage.verify_sse_support()
    logger.warning.assert_called_once()


def test_app_startup_fails_when_probe_fails(sse_on: None) -> None:
    from apps.runtime.app import app

    probe = AsyncMock(side_effect=RuntimeError("no kms"))
    with (
        patch("apps.runtime.app.verify_sse_support", probe),
        pytest.raises(RuntimeError, match="no kms"),
        TestClient(app),
    ):
        pass


def test_app_startup_rejects_invalid_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.runtime.app import app

    monkeypatch.setenv("MINIO_ENCRYPTION", "bogus")
    with pytest.raises(ValueError, match="Invalid MINIO_ENCRYPTION"), TestClient(app):
        pass


def test_app_starts_without_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.runtime.app import app

    monkeypatch.delenv("MINIO_ENCRYPTION", raising=False)
    with patch(f"{_MODULE}._minio_probe_client") as factory, TestClient(app):
        pass
    factory.assert_not_called()
