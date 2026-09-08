"""MinIO client for call artifact proxy routes and campaign CSV storage."""

from __future__ import annotations

import asyncio
import io
import os
from datetime import timedelta

from minio import Minio
from minio.error import S3Error


class MinIOStorage:
    """Thin async wrapper around the MinIO Python client."""

    def __init__(self) -> None:
        self.client = Minio(
            os.getenv("MINIO_ENDPOINT", "localhost:9000"),
            access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
            secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin123"),
            secure=os.getenv("MINIO_SECURE", "false").lower() in ("true", "1", "yes"),
        )
        self.default_bucket = os.getenv("MINIO_BUCKET", "voicera-calls")

    async def get_object(self, bucket_name: str, object_name: str):
        return await asyncio.to_thread(
            self.client.get_object,
            bucket_name,
            object_name,
        )

    async def get_object_bytes(self, object_key: str, bucket_name: str | None = None) -> bytes:
        bucket = bucket_name or self.default_bucket
        response = await self.get_object(bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    async def put_object_bytes(
        self,
        object_key: str,
        data: bytes,
        *,
        bucket_name: str | None = None,
        content_type: str = "text/csv",
    ) -> None:
        bucket = bucket_name or self.default_bucket
        await asyncio.to_thread(
            self.client.put_object,
            bucket,
            object_key,
            io.BytesIO(data),
            len(data),
            content_type=content_type,
        )

    def presigned_put_url(
        self,
        object_key: str,
        *,
        bucket_name: str | None = None,
        expiration_seconds: int = 1800,
    ) -> str:
        bucket = bucket_name or self.default_bucket
        return self.client.presigned_put_object(
            bucket,
            object_key,
            expires=timedelta(seconds=expiration_seconds),
        )

    def presigned_get_url(
        self,
        object_key: str,
        *,
        bucket_name: str | None = None,
        expiration_seconds: int = 3600,
    ) -> str:
        bucket = bucket_name or self.default_bucket
        return self.client.presigned_get_object(
            bucket,
            object_key,
            expires=timedelta(seconds=expiration_seconds),
        )

    def object_exists(self, bucket_name: str, object_name: str) -> bool:
        try:
            self.client.stat_object(bucket_name, object_name)
            return True
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                return False
            raise

    @staticmethod
    def parse_minio_url(url: str) -> tuple[str, str] | None:
        if not url or not url.startswith("minio://"):
            return None
        path = url.removeprefix("minio://")
        parts = path.split("/", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return None
        return parts[0], parts[1]
