---
title: Object storage (S3)
description: Where recordings, transcripts, campaign CSVs and knowledge-base PDFs live, and how to switch buckets between dev and prod.
---

VoicEra stores every file it produces or receives in one S3-compatible bucket:

| What | Key layout | Written by |
|---|---|---|
| Call recording | `{org_id}/{call_id}/recording.wav` | runtime, at call end |
| Provider (carrier) recording | `{org_id}/{call_id}/provider_recording.*` | runtime, recording webhook |
| Transcript | `{org_id}/{call_id}/transcript.txt` | runtime, at call end |
| Campaign source CSV | `campaigns/{org_id}/{uuid}_{name}.csv` | API, on upload |
| Knowledge-base PDF | `knowledge/{org_id}/{document_id}/{name}.pdf` | API, on upload |

The code talks to S3 through boto3 (`apps/api/app/storage/object_storage.py` and `apps/runtime/services/storage/object_storage.py`), so any S3-compatible endpoint works: infra S3, AWS, or a local MinIO container. Which bucket is used is configuration only.

| Environment | `S3_BUCKET` |
|---|---|
| Development / testing | `voicera-local-dev` |
| Production | the prod bucket |

The full variable list is in [Environment variables → Object storage](../../developer/reference/environment-variables.md#object-storage).

## Set up the dev bucket

Run once from a machine that can reach the endpoint:

```bash
pip install boto3
export S3_ENDPOINT_URL=https://s3.example.com
export S3_ACCESS_KEY_ID=<access key>
export S3_SECRET_ACCESS_KEY=<secret key>
export S3_BUCKET=voicera-local-dev

python scripts/s3_setup_bucket.py --create --expire-days 30
```

The script creates the bucket if it is missing, optionally sets a lifecycle rule that deletes objects older than N days (sensible for a dev bucket), then writes, reads, presigns and deletes a `_healthcheck/` object with exactly the client settings the services use. Re-running it is safe. If the bucket exists but the keys cannot access it, it stops with a 403 message.

Then put the same values in the root `.env` (see `.env.example`) and start the stack as usual. The MinIO container is no longer started by default.

## Production (Kubernetes)

1. Create the prod bucket the same way, with `S3_BUCKET=<prod bucket>` and no `--expire-days` unless a retention policy has been agreed.
2. Put the keys in a Secret and the rest in the ConfigMap for **api, arq-worker, campaign-orchestrator and runtime**:

   ```yaml
   # Secret
   S3_ACCESS_KEY_ID: <access key>
   S3_SECRET_ACCESS_KEY: <secret key>
   # ConfigMap
   S3_ENDPOINT_URL: https://s3.example.com
   S3_BUCKET: <prod bucket>
   S3_REGION: us-east-1
   S3_ADDRESSING_STYLE: path
   ```

3. Roll out. New calls write `s3://<prod bucket>/…` URIs immediately.
4. Remove the `MINIO_*` variables and the MinIO deployment and volume once old data has been copied (below) and verified.

Until the `S3_*` variables are present the services keep using the old `MINIO_*` ones, so the rollout order does not matter.

## Existing MinIO data

Call logs written before the switch hold `minio://voicera-calls/{org_id}/{call_id}/…` URIs. The API resolves them to `S3_BUCKET` + `S3_LEGACY_KEY_PREFIX` + the original key, so old recordings play as soon as the objects exist in S3.

Copy the old bucket with any S3 tool. Two layouts work:

```bash
# Keys copied as-is (S3_LEGACY_KEY_PREFIX stays empty)
rclone copy minio:voicera-calls s3infra:<prod bucket> --progress

# Old bucket kept as a folder, e.g. <prod bucket>/voicera-calls/...
rclone copy minio:voicera-calls s3infra:<prod bucket>/voicera-calls --progress
# then set S3_LEGACY_KEY_PREFIX=voicera-calls/
```

Campaign CSVs and knowledge-base PDFs are stored by bare key; with a prefix set, the API looks for them under the prefix when the bare key is missing.

## Encryption at rest

Uploads are not encrypted by VoicEra unless you ask for it. Set `S3_SSE=AES256` (keys managed by the store) or `S3_SSE=aws:kms` (plus `S3_SSE_KMS_KEY_ID` for a specific key) on api, arq-worker, campaign-orchestrator and runtime, and every recording, transcript, campaign CSV and knowledge-base PDF is written with that `ServerSideEncryption` header. Objects already in the bucket are not changed.

Not every S3-compatible store accepts the header, and one that does not rejects the upload. Check first, from a machine that reaches the endpoint:

```bash
S3_SSE=AES256 python scripts/s3_setup_bucket.py
```

The smoke test then uploads with encryption and confirms the stored object reports it (`sse     ok (AES256)`), or stops with an error that says the store refused it.

## Retention

Moving to S3 removes the disk-full failure, not the growth. Agree a retention period with the operators and set a lifecycle rule on the prod bucket (S3 lifecycle rules filter by key prefix or object tag, so per-org rules like `{org_id}/` work; a whole-bucket rule covers everything) so storage does not grow without bound.