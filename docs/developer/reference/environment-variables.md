---
title: Environment variables
description: Canonical reference for every VoicEra environment variable.
---

Every variable the VoicEra stack reads, its default, and whether you must set it. Values come from `.env.example`, `docker-compose.yaml`, `apps/api/app/config.py`, `apps/runtime/constants.py`, and `model-server/.env.example`.

<Note>
There are exactly **two** env files: one `.env` at the repository root, and a separate `model-server/.env`. There are no per-service env files. If you are following older documentation that describes five per-service `.env` files, that layout no longer exists.
</Note>

## The single root `.env`

Copy the template and edit it in place:

```bash
cp .env.example .env
```

Every service in `docker-compose.yaml` that needs configuration loads this one file through `env_file: - .env`. The API also reads it directly outside Docker: `apps/api/app/config.py` pins `env_file` to the repository root `.env`, resolved four directories up from `config.py`, so running `uvicorn` from `apps/api` still picks up the root file.

`make application-up` (which wraps `./scripts/start-application-services.sh`) generates `SECRET_KEY`, `INTERNAL_API_KEY`, and `PROVIDER_AUTH_ENCRYPTION_KEY` if they are missing. Prefer it over a bare `docker compose up` — the compose file's own header says a fresh checkout without `.env` will fail or come up misconfigured.

The model server is a separate stack with its own compose file and its own `model-server/.env`. See [Model server](#model-server) below.

## Infrastructure (Docker Compose)

These only affect how Compose wires the stack. Nothing in application code reads them.

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `FERRETDB_HOST_PORT` | `27018` | No | Host port published for FerretDB. The container still listens on `27017`. |
| `API_HOST_PORT` | `8000` | No | Host port published for the API. |
| `RUNTIME_HOST_PORT` | `7860` | No | Host port published for the runtime. |

## API

Read by `apps/api/app/config.py` (a pydantic `BaseSettings`), plus the ARQ worker and the campaign orchestrator, which run the same image.

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `MONGODB_HOST` | `localhost` | No | FerretDB host. Compose forces this to `mongodb`, the FerretDB network alias. |
| `MONGODB_PORT` | `27017` in code, `27018` in `.env.example` | No | FerretDB port. Compose forces `27017` because containers talk to the container port. |
| `MONGODB_USER` | `admin` | No | Also becomes `POSTGRES_USER` on the `postgres` service. |
| `MONGODB_PASSWORD` | `admin123` | No | Also becomes `POSTGRES_PASSWORD`. Change it for anything but a local stack. |
| `MONGODB_DATABASE` | `voicera` | No | Database name. |
| `MONGODB_AUTH_SOURCE` | empty | No | Leave empty for FerretDB — it authenticates through PostgreSQL users (SCRAM). |
| `MONGODB_AUTH_MECHANISM` | empty | No | Optional `SCRAM-SHA-256`. Usually omit and let the driver negotiate. |
| `API_V1_PREFIX` | `/api/v1` | No | Prefix every router is mounted under. Not present in `.env.example`. |
| `PROJECT_NAME` | `Voicera API` | No | Title in the OpenAPI document and the root response. |
| `VERSION` | `0.1.0` | No | Version in the OpenAPI document. |
| `DEBUG` | `False` | No | Sets log level to `DEBUG`. See [Compose override precedence](#compose-override-precedence). |
| `SECRET_KEY` | none | **Yes** | JWT signing key. Compose declares it `${SECRET_KEY:?...}` and refuses to start without it. |
| `INTERNAL_API_KEY` | empty | Effectively yes | Shared key for `X-API-Key` service routes. When empty, every such route returns `500`. |
| `PROVIDER_AUTH_ENCRYPTION_KEY` | empty | Effectively yes | Fernet key encrypting `ProviderAuth` credential blobs. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | No | JWT lifetime. Not present in `.env.example`. |
| `JWT_ALGORITHM` | `HS256` | No | JWT signing algorithm. Not present in `.env.example`. |
| `MAILTRAP_API_TOKEN` | empty | No | Mailtrap token for password-reset email. Empty disables the mail path. |
| `MAILTRAP_FROM_EMAIL` | `noreply@voicera.com` | No | Sender address on reset emails. |
| `MAILTRAP_FROM_NAME` | `Voicera` | No | Sender name on reset emails. |
| `FRONTEND_URL` | `http://localhost:3000` | No | Base URL used to build the password-reset link. |
| `VOICE_SERVER_BASE_URL` | empty | Yes for telephony | Public base URL of the runtime. Required when creating or updating a telephony agent. |
| `ENABLE_CAMPAIGN_ORCHESTRATOR` | `True` | No | Lets API startup spawn the orchestrator. Docker runs it as a separate service instead. |

Rotating `PROVIDER_AUTH_ENCRYPTION_KEY` makes every stored `ProviderAuth` blob undecryptable. Existing provider credentials must be re-entered after a rotation.

Generate the three secrets by hand if you are not using the start script:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Runtime

`apps/runtime/constants.py` reads these with `os.getenv` at call time, so a value takes effect on the next call rather than at import.

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `API_BASE_URL` | `http://localhost:8000/api/v1` | No | Where the runtime calls the API. Compose overrides it to `http://api:8000/api/v1`. |
| `VOICE_SERVER_BASE_URL` | empty | Yes for telephony | Rewritten to `ws://` or `wss://` to build the media WebSocket URL in the Stream XML. |
| `SAMPLE_RATE` | `8000` | No | Telephony audio sample rate for Stream XML and provider serializers. `8000` or `16000`. |
| `WEBSOCKET_SAMPLE_RATE` | `16000` | No | Sample rate for browser WebSocket agents (protobuf/RTVI clients). |
| `RUNTIME_HOST` | `0.0.0.0` | No | Bind address, read in `apps/runtime/app.py` when started through `main()`. |
| `RUNTIME_PORT` | `7860` | No | Bind port, read in `apps/runtime/app.py` when started through `main()`. |
| `INTERNAL_API_KEY` | empty | Effectively yes | The runtime's `X-API-Key` for service routes on the API. |
| `TELEPHONY_BULK_STATUS_POLL_SECS` | `30` | No | Bulk-outbound campaign status poll interval (API worker). |
| `TELEPHONY_BULK_STATUS_POLL_MAX_ROUNDS` | `120` | No | Max bulk status polls; `0` disables. |

### Vodafone Idea (VI)

OBD username, password, and DNI/flow pairs come from **Integrations ProviderAuth** only (`auth_id`, `auth_token`, `dni_flows`) — not from process env. Configure them via `POST /auth` for provider `vi`. There are no VI-specific runtime env vars.

Portal DIY Streaming Object should target `wss://<VOICE_SERVER_BASE_URL host>/vi/stream` (legacy: `/vi/agent/{agent_id}`). Link the agent’s number so it matches the DNI on the DIY flow (E.164 `+91…` is fine; runtime also accepts 10-digit national forms). Agent routing on `/vi/stream` uses DNI/CLI Numbers lookup (or `agent_id` + optional `org_id` in stream `custom_parameters`) — not env defaults.

`RUNTIME_HOST` and `RUNTIME_PORT` are absent from `.env.example`; they only matter when you start the runtime through its `main()` entry point rather than a uvicorn command line.

## Dashboard

`NEXT_PUBLIC_*` variables are baked into the JavaScript bundle at build time. They are **not** secrets — anyone can read them in the shipped bundle.

| Variable | Default | Required | Notes |
| --- | --- | --- | --- |
| `FRONTEND_HOST_PORT` | `3000` | No | Host port published for the `frontend` container. |
| `NEXT_PUBLIC_API_URL` | `/api/v1` | No | Base path the browser calls for every REST request. Same-origin by default — see below. |
| `API_PROXY_TARGET` | `http://api:8000` | No | Where the Next.js server forwards `/api/v1/*` internally. Read at **runtime**, not build time, so changing it needs only a container restart, not a rebuild. |
| `RUNTIME_PROXY_TARGET` | `http://runtime:7860` (Compose) / `http://127.0.0.1:7860` (local default) | No | Where the Next.js server forwards `/agent/:orgId/:agentId` WebSockets for browser test calls. Read at runtime. |
| `ALLOWED_DEV_ORIGINS` | `voicera.johnaic.com` | No | Hosts Next.js accepts dev-origin requests from. |

Both REST and the browser test-call WebSocket are same-origin from the browser: `/api/v1/...` and `/agent/...` hit the dashboard host, and `next.config.ts` rewrites them to `API_PROXY_TARGET` and `RUNTIME_PROXY_TARGET` server-side. Neither FastAPI nor the runtime need a public hostname of their own for the dashboard.

`FRONTEND_URL` in the [API](#api) section is a separate variable: the API uses it to build password-reset links, and it is read server-side.

## Redis and campaigns

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `REDIS_PASSWORD` | `redissecret` | No | Password for the `redis` service. Interpolated into `REDIS_URL` by Compose. |
| `REDIS_URL` | `redis://localhost:6379` in code, `redis://:redissecret@localhost:6379` in `.env.example` | No | ARQ job queue and campaign pub/sub. Compose overrides it to `redis://:${REDIS_PASSWORD}@redis:6379`. |
| `CAMPAIGN_BATCH_SIZE` | `10` | No | Queued runs the orchestrator processes per campaign batch. |
| `DEFAULT_ORG_CONCURRENCY_LIMIT` | `10` | No | Default maximum concurrent calls per organisation. |
| `CAMPAIGN_MAX_CSV_BYTES` | `5242880` (5 MiB) | No | Maximum campaign CSV upload size. Not present in `.env.example`. |

`DEFAULT_ORG_CONCURRENCY_LIMIT` is read twice: as a pydantic setting in `apps/api/app/config.py` and directly with `os.getenv` in `apps/api/app/constants/campaign.py`, where it is clamped to a minimum of `1`.

## Object storage

An S3-compatible bucket holds call recordings, transcripts, campaign source CSVs (`campaigns/…`), and knowledge-base PDFs. The API, ARQ worker, campaign orchestrator and runtime all use the same variables. Use `voicera-local-dev` for development and testing and a separate bucket in production; only `S3_BUCKET` changes between them. Create or verify a bucket with `python scripts/s3_setup_bucket.py --create`.

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `S3_ENDPOINT_URL` | — | Yes (on-prem S3) | S3 API endpoint, e.g. `https://s3.example.com`. Unset means AWS. |
| `S3_ACCESS_KEY_ID` | — | Yes | Access key. Falls back to `AWS_ACCESS_KEY_ID`. |
| `S3_SECRET_ACCESS_KEY` | — | Yes | Secret key. Falls back to `AWS_SECRET_ACCESS_KEY`. |
| `S3_REGION` | `us-east-1` | No | Signing region. Falls back to `AWS_DEFAULT_REGION`. |
| `S3_BUCKET` | `voicera-local-dev` | No | Bucket for every object the platform stores. |
| `S3_ADDRESSING_STYLE` | `path` | No | `path` (most on-prem S3), `virtual` or `auto`. |
| `S3_VERIFY_SSL` | `true` | No | Set `false` only for testing against self-signed endpoints. |
| `S3_CA_BUNDLE` | — | No | Path to a CA bundle when the endpoint uses a private CA. |
| `S3_PUBLIC_ENDPOINT_URL` | — | No | Endpoint used to sign presigned URLs given to browsers (campaign CSV download) when `S3_ENDPOINT_URL` is internal-only. |
| `S3_LEGACY_KEY_PREFIX` | — | No | Prefix under which pre-migration MinIO objects were copied (e.g. `voicera-calls/`). Lets old `minio://` links and KB/CSV keys resolve. |
| `S3_MAX_POOL_CONNECTIONS` | `32` | No | boto3 HTTP connection pool size per process. |
| `S3_SSE` | — (off) | No | Server-side encryption requested on every upload: `AES256` or `aws:kms`. Leave empty unless the store supports it, or uploads are rejected. Any other value stops the service with an error. |
| `S3_SSE_KMS_KEY_ID` | — | No | KMS key id/ARN, used only with `S3_SSE=aws:kms`. Empty uses the store's default KMS key. |

Recordings and transcripts are never served to browsers directly: the API streams them through `/api/v1/calls/{call_id}/…`, so only the services need network access to the endpoint.

**Backward compatibility.** If no `S3_*` value is set, each falls back to its old `MINIO_*` counterpart (`MINIO_ENDPOINT` + `MINIO_SECURE`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`), so an existing deployment keeps working until the new variables are added. `S3_*` always wins when both are set.

**Local MinIO (optional).** `docker compose --profile local-minio up -d` starts the `minio` and `minio-init` services (`MINIO_API_PORT`, `MINIO_CONSOLE_PORT`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`). Point `S3_ENDPOINT_URL=http://minio:9000` and the `S3_*` keys at the root credentials to use it instead of infra S3.

## Knowledge base

Read only by the API. Chroma is embedded, not a service.

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `CHROMA_BASE_DIR` | `app/rag/chroma_data` | No | Root directory for per-organisation Chroma stores. Compose sets `/app/app/rag/chroma_data`, backed by the `voicera_oss_chroma_data` volume. |
| `KB_EMBEDDING_API_KEY` | empty | Yes to use RAG | OpenAI API key for embeddings. A single global key, not per-organisation. |
| `KB_EMBEDDING_MODEL` | `text-embedding-3-small` | No | Embedding model for ingest and retrieval. |
| `KB_MAX_UPLOAD_BYTES` | `26214400` (25 MiB) | No | Maximum PDF upload size. Not present in `.env.example`. |

<Warning>
`KB_EMBEDDING_API_KEY` is described in `apps/api/app/config.py` as a temporary global key. Every organisation's documents are embedded through the same account.
</Warning>

## Model server

A separate stack with its own compose file and its own `model-server/.env`. Copy `model-server/.env.example` to `model-server/.env`. The variables below are the ones you set to run it; the long tail of `CORE_*`, `MIO_*`, and MPS tuning knobs ships commented out at the values upstream benchmarks at, and leaving them commented is the supported configuration.

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `COMPOSE_PROFILES` | `stt,tts` | No | Which slots run. Slot names, not model names. |
| `STT_MODEL` | `indic-conformer` | No | Folder under `stt/` that fills the STT slot. Empty means the slot is not deployed. |
| `TTS_MODEL` | `indic-parler` | No | Folder under `tts/` that fills the TTS slot. |
| `LLM_MODEL` | empty | No | Folder under `llm/` that fills the LLM slot. Empty by default. |
| `GATEWAY_PORT` | `8100` | No | The only published port in the model-server stack. |
| `STT_UPSTREAM` | `http://stt:8001` | No | Override only to point the slot at a different host. Commented out by default. |
| `TTS_UPSTREAM` | `http://tts:8002` | No | As above. |
| `LLM_UPSTREAM` | `http://llm:8003` | No | As above. |
| `GPU_DEVICE_IDS` | `1` | No | GPU reserved for the model containers. |
| `INDIC_NEMO_PATH` | `/app/models/IndicConformer.nemo` | No | In-container path to the STT checkpoint. |
| `BHILI_ENABLE` | `no` | No | Whether to load the Bhili checkpoint. |
| `BHILI_NEMO_PATH` | empty | No | Path to the Bhili checkpoint when enabled. |
| `HF_TOKEN` | empty | Yes for gated repos | HuggingFace token with access to `ai4bharat/indic-parler-tts`. |
| `HF_CACHE_VOLUME` | `voicera-prod_hf_cache` | No | External cache volume when using the shared-cache overlay. |
| `USE_SHARED_HF_CACHE` | empty | No | Recorded by `scripts/start-model-server.sh` so a later restart keeps your choice. |
| `HF_HUB_OFFLINE` | `0` | No | `1` blocks HuggingFace fetches, turning a gated `401` into a clean miss. |
| `NEMO_CONTEXT_PATH` | `../../ai4bharat_nemo` | No | Local checkout of the AI4Bharat NeMo fork, passed in as a build context. |
| `VLLM_MAX_MODEL_LEN` | `8192` | No | vLLM context length for the LLM slot. |
| `VLLM_MAX_NUM_SEQS` | `20` | No | vLLM concurrent sequence limit. |
| `VLLM_GPU_MEMORY_UTILIZATION` | `0.10` | No | Deliberately far below vLLM's `0.9` default: the GPU is shared through MPS, which does not partition memory. |
| `VLLM_QUANTIZATION` | empty | No | Empty means bf16. Set `fp8` only if memory becomes the constraint. |

A slot counts as deployed when its `*_MODEL` is named. That is the same variable that picks the build folder, so Compose and the gateway cannot disagree about what is running.

## Compose override precedence

Compose applies `env_file` first, then the `environment:` block, and `environment:` wins. Several variables are therefore different inside the stack than in your `.env`:

| Variable | Value in `.env.example` | Value inside the stack | Why |
|---|---|---|---|
| `MONGODB_HOST` | `localhost` | `mongodb` | The FerretDB service's network alias on `app-network`. |
| `MONGODB_PORT` | `27018` | `27017` | Containers reach the container port; `27018` is only the host publication. |
| `API_BASE_URL` | `http://localhost:8000/api/v1` | `http://api:8000/api/v1` | The runtime reaches the API by service name. |
| `REDIS_URL` | `redis://:redissecret@localhost:6379` | `redis://:${REDIS_PASSWORD}@redis:6379` | Rebuilt from `REDIS_PASSWORD` against the service name. |
| `CHROMA_BASE_DIR` | `app/rag/chroma_data` | `/app/app/rag/chroma_data` | Absolute path matching the volume mount. |

Editing one of these in `.env` changes nothing for the containers. To change them inside the stack, edit `docker-compose.yaml`.

`DEBUG` is the one variable deliberately **not** interpolated in `docker-compose.yaml` — it reaches the API through `env_file` only. The compose file comments why: host shells frequently export `DEBUG=release`, which would override a boolean `False` from `.env`. `apps/api/app/config.py` defends against this too, with a validator that treats only `1`, `true`, `yes`, and `on` as true and everything else as false, so an exported `DEBUG=release` degrades to `False` instead of crashing settings parsing.

## Variables with no default

Three variables have no usable default. `SECRET_KEY` is the only one Compose enforces:

| Variable | What happens when unset |
|---|---|
| `SECRET_KEY` | Compose declares it `${SECRET_KEY:?SECRET_KEY must be set to a strong secret}` on `api`, `arq-worker`, and `campaign-orchestrator`. The stack refuses to start. Outside Docker the API generates a temporary random key at import and logs a warning, so every restart invalidates every issued token. |
| `INTERNAL_API_KEY` | Defaults to empty and Compose passes it through as empty. Every `X-API-Key` route returns `500 Internal API key not configured`, breaking inbound-call registration and RAG retrieval. |
| `PROVIDER_AUTH_ENCRYPTION_KEY` | Defaults to empty. Provider credentials cannot be encrypted or read back. |

`VOICE_SERVER_BASE_URL` is a fourth: it defaults to empty and only matters once you create a telephony agent, at which point it is required.

## Related

* [Ports and defaults](ports-and-defaults)
* [Endpoints cheatsheet](../../api-reference/endpoints-cheatsheet)
* [Docker Compose](../../guides/deployment/docker-compose)
* [Security hardening](../../guides/deployment/security-hardening)
* [Generated secrets and defaults](../../guides/quickstart/secrets-and-defaults)