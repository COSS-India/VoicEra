#!/usr/bin/env python3
"""Create (if needed) and verify the VoicEra object-storage bucket on S3.

Uses the same environment variables as the API and runtime, so a passing run
means the services will be able to read and write with the same settings:

    S3_ENDPOINT_URL        e.g. https://s3.example.com
    S3_ACCESS_KEY_ID       (or AWS_ACCESS_KEY_ID)
    S3_SECRET_ACCESS_KEY   (or AWS_SECRET_ACCESS_KEY)
    S3_REGION              (or AWS_DEFAULT_REGION, default us-east-1)
    S3_BUCKET              default voicera-local-dev
    S3_ADDRESSING_STYLE    default path
    S3_VERIFY_SSL / S3_CA_BUNDLE
    S3_SSE                 optional: AES256 or aws:kms (+ S3_SSE_KMS_KEY_ID)

Examples:

    # check access only (no changes)
    python scripts/s3_setup_bucket.py

    # create voicera-local-dev if missing, then run a write/read/delete check
    python scripts/s3_setup_bucket.py --create

    # dev bucket: auto-delete objects older than 30 days
    python scripts/s3_setup_bucket.py --create --expire-days 30

    # check that the store accepts server-side encryption before enabling it
    S3_SSE=AES256 python scripts/s3_setup_bucket.py
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def _env(*keys: str, default: str = "") -> str:
    for key in keys:
        value = (os.getenv(key) or "").strip()
        if value:
            return value
    return default


def make_client(endpoint_url: str | None, region: str) -> Any:
    verify_raw = _env("S3_VERIFY_SSL", default="true").lower()
    verify: bool | str = _env("S3_CA_BUNDLE") or verify_raw in {"1", "true", "yes", "on"}
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=_env("S3_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID") or None,
        aws_secret_access_key=_env("S3_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY") or None,
        region_name=region,
        verify=verify,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": _env("S3_ADDRESSING_STYLE", default="path")},
            connect_timeout=10,
            read_timeout=60,
            retries={"max_attempts": 5, "mode": "adaptive"},
            # boto3 >= 1.36 adds CRC checksums / aws-chunked uploads by default;
            # many S3-compatible stores reject them (XAmzContentSHA256Mismatch).
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


SSE_MODES = ("AES256", "aws:kms")


def sse_params() -> dict[str, str]:
    raw = _env("S3_SSE")
    if raw.lower() in {"", "off", "none", "false", "0", "no"}:
        return {}
    mode = next((m for m in SSE_MODES if m.lower() == raw.lower()), None)
    if mode is None:
        sys.exit(f"ERROR: invalid S3_SSE={raw!r}; use AES256, aws:kms or leave empty.")
    params = {"ServerSideEncryption": mode}
    kms_key_id = _env("S3_SSE_KMS_KEY_ID")
    if mode == "aws:kms" and kms_key_id:
        params["SSEKMSKeyId"] = kms_key_id
    return params


def bucket_exists(s3, bucket: str) -> bool:
    try:
        s3.head_bucket(Bucket=bucket)
        return True
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchBucket", "NotFound"}:
            return False
        if code in {"403", "AccessDenied"}:
            sys.exit(
                f"ERROR: bucket '{bucket}' exists but these credentials cannot access it "
                f"(403). Ask the storage admin to grant access."
            )
        raise


def create_bucket(s3, bucket: str, region: str) -> None:
    kwargs: dict = {"Bucket": bucket}
    if region and region != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
    s3.create_bucket(**kwargs)


def set_expiry(s3, bucket: str, days: int) -> None:
    s3.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": f"expire-after-{days}-days",
                    "Status": "Enabled",
                    "Filter": {"Prefix": ""},
                    "Expiration": {"Days": days},
                }
            ]
        },
    )


def smoke_test(s3, bucket: str) -> None:
    key = f"_healthcheck/{uuid.uuid4()}.txt"
    payload = b"voicera s3 healthcheck"
    sse = sse_params()
    try:
        s3.put_object(
            Bucket=bucket, Key=key, Body=payload, ContentType="text/plain", **sse
        )
    except ClientError as exc:
        if sse:
            sys.exit(
                f"ERROR: upload with S3_SSE={sse['ServerSideEncryption']} was rejected "
                f"({exc.response.get('Error', {}).get('Code')}). This store may not "
                f"support server-side encryption; leave S3_SSE empty or ask the "
                f"storage admin to enable it."
            )
        raise
    print(f"  put     s3://{bucket}/{key}")
    head = s3.head_object(Bucket=bucket, Key=key)
    assert head["ContentLength"] == len(payload), head
    print("  head    ok")
    if sse:
        applied = head.get("ServerSideEncryption")
        if applied != sse["ServerSideEncryption"]:
            sys.exit(
                f"ERROR: requested S3_SSE={sse['ServerSideEncryption']} but the stored "
                f"object reports ServerSideEncryption={applied!r}."
            )
        print(f"  sse     ok ({applied})")
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    assert body == payload, body
    print("  get     ok")
    url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=60
    )
    print(f"  presign ok ({url.split('?', 1)[0]}?...)")
    s3.delete_object(Bucket=bucket, Key=key)
    print("  delete  ok")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--bucket", default=_env("S3_BUCKET", default="voicera-local-dev"))
    ap.add_argument("--endpoint-url", default=_env("S3_ENDPOINT_URL") or None)
    ap.add_argument(
        "--region", default=_env("S3_REGION", "AWS_DEFAULT_REGION", default="us-east-1")
    )
    ap.add_argument("--create", action="store_true", help="create the bucket if it is missing")
    ap.add_argument(
        "--expire-days",
        type=int,
        default=0,
        help="set a lifecycle rule deleting objects older than N days (0 = leave as is)",
    )
    ap.add_argument("--skip-smoke-test", action="store_true")
    args = ap.parse_args()

    print(f"endpoint: {args.endpoint_url or '(AWS default)'}")
    print(f"bucket:   {args.bucket}")
    s3 = make_client(args.endpoint_url, args.region)

    if bucket_exists(s3, args.bucket):
        print("bucket exists")
    elif args.create:
        create_bucket(s3, args.bucket, args.region)
        print("bucket created")
    else:
        sys.exit(f"ERROR: bucket '{args.bucket}' does not exist. Re-run with --create.")

    if args.expire_days > 0:
        set_expiry(s3, args.bucket, args.expire_days)
        print(f"lifecycle: objects expire after {args.expire_days} days")

    if not args.skip_smoke_test:
        print("smoke test:")
        smoke_test(s3, args.bucket)

    print(f"OK — set S3_BUCKET={args.bucket} for the api and runtime services.")


if __name__ == "__main__":
    main()