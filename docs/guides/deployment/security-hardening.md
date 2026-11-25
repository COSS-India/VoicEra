---
title: Security hardening
description: What to change before exposing a VoicEra deployment.
---

VoicEra ships development defaults so the stack starts on the first try. Work through this page before anything is reachable beyond your laptop.

## Data ownership

Everything VoicEra stores — call recordings, transcripts, knowledge-base documents, provider credentials — stays in the Postgres, MinIO, and FerretDB containers you run. Nothing is sent to a VoicEra-operated service, and there is no telemetry or usage reporting baked into the platform. The only external network calls the stack makes are the ones you configure yourself: your chosen STT/TTS/LLM providers, and your telephony provider. Self-hosting every model (see [Self-hosted models](self-hosted-models)) removes those too, for a fully air-gapped deployment.

## Change every default

`.env.example` ships these passwords blank and the start script generates them on first run. `docker-compose.yaml` refuses to start while any of them is blank. The values below are the old defaults that installs created before that change still use — all public knowledge, and the start script warns if it finds them.

| Variable | Ships as | Protects |
| --- | --- | --- |
| `MONGODB_PASSWORD` | formerly `admin123` | The database, **and** the PostgreSQL superuser |
| `MINIO_ROOT_PASSWORD` / `MINIO_SECRET_KEY` | formerly `minioadmin123` | Recordings and transcripts |
| `MINIO_ROOT_USER` / `MINIO_ACCESS_KEY` | `minioadmin` | Same |
| `REDIS_PASSWORD` | formerly `redissecret` | Job queue, campaign events, concurrency slots |

<Warning>
`MONGODB_USER` and `MONGODB_PASSWORD` become the PostgreSQL credentials too. Changing them after the volume exists does **not** update the Postgres user — set them before the first start, or change the password inside Postgres as well.
</Warning>

## The three generated secrets

`make application-up` (which wraps `./scripts/start-application-services.sh`) generates these when blank and never overwrites them.

| Secret | Protects | Rotation |
| --- | --- | --- |
| `SECRET_KEY` | JWT signatures (HS256) | Invalidates all tokens; users log in again |
| `INTERNAL_API_KEY` | Service-to-service auth | Update API and runtime together |
| `PROVIDER_AUTH_ENCRYPTION_KEY` | Fernet encryption of stored credentials | **One-way — see below** |
| `MINIO_KMS_SECRET_KEY` | Recordings and transcripts at rest (optional, not generated) | **One-way — see below** |

<Warning>
`PROVIDER_AUTH_ENCRYPTION_KEY` cannot be rotated. There is no re-encryption tool: changing or losing it makes every stored provider credential permanently undecryptable, and every organisation must re-enter every key. Back it up alongside the database, and store it with the same protection.
</Warning>

<Warning>
`MINIO_KMS_SECRET_KEY` cannot be rotated or removed. MinIO also encrypts its own configuration and IAM data with it, even if `MINIO_ENCRYPTION` was never enabled. If the key is changed or removed, MinIO cannot load its configuration and encrypted recordings and transcripts cannot be read until the original key is restored. If the key is lost, they are unrecoverable. Back it up alongside the database, never with the MinIO volume backup.
</Warning>

<Warning>
If `SECRET_KEY` is blank the API does **not** fail. `apps/api/app/auth.py` logs a warning and generates a temporary key at import — so tokens die on every restart and replicas reject each other's tokens. Verify it is set:

```bash
grep '^SECRET_KEY=' .env
```
</Warning>

Generate:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep them out of files on disk in production — inject from a secret manager. Every variable the stack reads, not just the security-relevant ones, is in [Environment variables](../../developer/reference/environment-variables).

## CORS

`apps/api/app/main.py` sets:

```python
allow_origins=["*"], allow_credentials=True
```

Any origin can call the API with credentials. Restrict it to the origins that actually need it and rebuild.

## The internal API key

`INTERNAL_API_KEY` is a **single shared credential with organisation-wide reach**. `POST /users/bot/token` exchanges it plus an `org_id` for a token with role `admin` in that organisation — for any organisation.

| Rule | Why |
| --- | --- |
| Never send it from a browser | It is not a user credential |
| Never expose the routes that accept it publicly | They bypass user auth by design |
| Rotate on any suspicion | One value protects every tenant |

## The unauthenticated runtime endpoints

<Warning>
`GET|POST /answer` and `WS /agent/{org_id}/{agent_id}` have **no authentication**. They must be publicly reachable for telephony to work, and the runtime resolves everything from the path — so anyone who learns an org and agent id pair can open a pipeline session and spend your model credits.
</Warning>

Mitigations:

* Rate limit `/answer` and `/agent` at the proxy.
* IP-allowlist your telephony provider's published ranges.
* Treat org and agent ids as semi-secret — do not put them in public pages or client-side code.
* Monitor call volume for unexplained sessions.

## Network exposure

Publish only what must be public:

| Service | Expose |
| --- | --- |
| API `:8000` | Behind TLS, to your clients |
| Runtime `:7860` | Behind TLS, to your telephony provider |
| FerretDB `:27018` | **Never publicly.** Bind to localhost or drop the mapping. |
| MinIO `:9000` | Private |
| MinIO console `:9001` | **Never publicly.** It is an admin UI. |
| Model gateway `:8100` | Private only — it has no authentication |
| PostgreSQL, Redis | Already unpublished; keep it that way |

To stop publishing a port, remove its `ports:` entry or bind it to loopback:

```yaml
ports:
  - "127.0.0.1:27018:27017"
```

## TLS

Telephony providers require HTTPS for webhooks and WSS for audio, so TLS is mandatory rather than optional. Terminate at a reverse proxy — see [Production deployment](production) for a working nginx configuration, including the WebSocket upgrade headers and the long read timeouts calls need.

For Redis over TLS use a `rediss://` URL; the ARQ settings enable TLS when they see that scheme.

## Client IP in the audit log

Audit events record the client IP as seen by the API. The browser reaches the API through the frontend's `/api/v1` rewrite, so by default each event records the frontend container's address. To record the client's address, configure the following:

1. **A reverse proxy in front of the frontend that sets `X-Forwarded-For`.** For example, nginx with `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`. The Next.js rewrite forwards this header to the API but does not set it.
2. **`FORWARDED_ALLOW_IPS` on the API, listing the frontend container and that proxy.** uvicorn trusts `X-Forwarded-For` only from these addresses. In Docker Compose, use the Compose network's CIDR (`docker network inspect <project>_app-network`), for example `FORWARDED_ALLOW_IPS=172.18.0.0/16`. That also covers the nginx setup in [Production deployment](production): nginx proxies to the published API port, so its requests reach the container from the network's gateway address.

<Warning>
Do not set `FORWARDED_ALLOW_IPS=*` while the API port is directly reachable. The API would then accept `X-Forwarded-For` from any client, and the recorded IP could not be trusted.
</Warning>

## Email enumeration

<Warning>
`GET /users/check/{email}` is **public and unauthenticated**, and confirms whether an account exists. Rate limit it at the proxy, or require authentication if you do not need the invite-flow convenience.
</Warning>

## Health probes

`GET /health` returns HTTP **200 even when the database is down** — only the body changes to `"status": "degraded"`. Configure probes to parse the body, or a broken API will look healthy.

## Images and dependencies

* `minio/minio:latest` is unpinned — pin a digest for reproducible deployments. The FerretDB, Postgres, and Redis images are already pinned.
* Rebuild periodically to pick up base-image security updates.
* VoicEra has no CI, so nothing scans dependencies automatically. Run `pip-audit` or equivalent yourself.

## Log hygiene

Logs go to `json-file`, rotating at 10 MB with three files kept. Before shipping them anywhere central, confirm no provider keys or tokens appear — and note that `DEBUG=True` substantially increases what is logged. Keep it `False` in production.

## Data protection

You hold call recordings, transcripts, and contact lists. That is regulated data in most jurisdictions.

* Encrypt volumes at rest, and enable [object encryption](#encryption-at-rest) for recordings and transcripts.
* Set a retention policy — nothing expires automatically. The audit log (`Events`) is the exception: events older than `EVENTLOG_RETENTION_DAYS` (minimum 365) are purged daily.
* Restrict MinIO access; artifacts are served through the authenticated API proxy, so the bucket never needs to be public. The audit log records access through the API only; access made directly to MinIO (console or `mc`) is not recorded.
* Remember `docker compose down -v` destroys all of it irreversibly.

## Encryption at rest

Set `MINIO_ENCRYPTION=sse-s3` to have MinIO encrypt new call recordings and transcripts (SSE-S3, AES-256) with its built-in KMS. Reads are unchanged; MinIO decrypts transparently. Existing objects, campaign CSVs, and knowledge-base PDFs are not encrypted.

This protects against theft of disks, volumes, and backups. It does not protect against anyone holding MinIO credentials, or traffic on the wire (use `MINIO_SECURE=true`).

To enable:

1. Generate the key once and back it up (see the warning under [The three generated secrets](#the-three-generated-secrets)):

   ```bash
   echo "MINIO_KMS_SECRET_KEY=voicera-key:$(openssl rand -base64 32)" >> .env
   ```

2. Set `MINIO_ENCRYPTION=sse-s3` in `.env`.
3. Run `docker compose up -d minio runtime`. The runtime logs `Object storage SSE probe passed`.

At startup the runtime writes and deletes a small probe object under `_system/sse-probe/` and refuses to start if it was not encrypted or storage is unreachable. With encryption on, MinIO is therefore a hard startup dependency of the runtime.

Every service that loads `.env` through `env_file` (`api`, the workers, `runtime`, `frontend`) can also see the key. To avoid that, pass it to `docker compose` from your shell or secret manager instead of `.env`.

To disable, set `MINIO_ENCRYPTION=none` and keep `MINIO_KMS_SECRET_KEY` — existing encrypted objects still need it.

The built-in KMS uses one static key with no rotation or audit trail. Deployments that need rotation should use MinIO KES with an external KMS.

## Checklist

- [ ] `MONGODB_PASSWORD` changed
- [ ] `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` changed
- [ ] `REDIS_PASSWORD` changed
- [ ] `SECRET_KEY` set and non-empty
- [ ] `INTERNAL_API_KEY` set and non-empty
- [ ] `PROVIDER_AUTH_ENCRYPTION_KEY` set and backed up
- [ ] `MINIO_KMS_SECRET_KEY` set, backed up separately from MinIO data, `MINIO_ENCRYPTION=sse-s3`
- [ ] `SECRET_KEY` identical across API replicas
- [ ] CORS restricted
- [ ] TLS on the API and runtime
- [ ] FerretDB, MinIO console, and the model gateway not publicly reachable
- [ ] Rate limiting on `/answer`, `/agent`, and `/users/check`
- [ ] Reverse proxy sets `X-Forwarded-For`, and `FORWARDED_ALLOW_IPS` lists the frontend and proxy
- [ ] `DEBUG=False`
- [ ] Volumes encrypted, retention policy set
- [ ] Backups tested by restoring

## Related

* [Production deployment](production)
* [Generated secrets and defaults](../quickstart/secrets-and-defaults)
* [Environment variables](../../developer/reference/environment-variables)
* [Provider credentials](../../developer/reference/provider-auth)
* [Multi-tenancy and roles](../../developer/reference/multi-tenancy)
