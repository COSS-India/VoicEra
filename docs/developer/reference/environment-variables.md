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
| `MINIO_API_PORT` | `9000` | No | Host port for the MinIO S3 API. |
| `MINIO_CONSOLE_PORT` | `9001` | No | Host port for the MinIO web console. |
| `MINIO_ROOT_USER` | `minioadmin` | No | MinIO root account, used by the `minio` and `minio-init` services. |
| `MINIO_ROOT_PASSWORD` | `minioadmin123` | No | MinIO root password. Change it before exposing MinIO. |
| `MINIO_BUCKET` | `voicera-calls` | No | Bucket `minio-init` creates for call artifacts and knowledge-base objects. |

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
| `PLATFORM_PROVIDER_AUTH` | empty | No | JSON map of provider id → secret fields, used when an organisation has not connected that provider itself. Empty disables the fallback. |
| `SANDBOX_SEED_AGENTS` | `False` in code, `True` in `.env.example` | No | Seed the six demo agents in `apps/api/app/seed/default_agents.json` into every newly created organisation. |

Rotating `PROVIDER_AUTH_ENCRYPTION_KEY` makes every stored `ProviderAuth` blob undecryptable. Existing provider credentials must be re-entered after a rotation.

`PLATFORM_PROVIDER_AUTH` is validated against the provider catalog at startup: an unknown provider id, a non-secret field, or a missing required secret aborts the API rather than failing at the first call. Organisation-owned credentials always win over it, and telephony providers are never resolved from it — a platform telephony key would let any signup provision applications on the platform's account. Set it together with `RATE_LIMIT_ENABLED=True`: the limits layer is what bounds the spend on the platform's own keys.

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

## Rate limiting and abuse control

See `docs/developer/rate-limiting-plan.md` for the design. All read by `apps/api/app/config.py`. `apps/runtime` reads four of them directly — `RATE_LIMIT_ENABLED`, `MAX_CALL_DURATION_SECONDS`, `MAX_CALL_DURATION_CEILING_SECONDS` (the duration guard) and `RUNTIME_SESSION_SECRET` — via `apps/runtime/constants.py`. Both services share the root `.env`, so one value configures both.

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `RATE_LIMIT_ENABLED` | `False` | No | Master switch. Every dependency below is a no-op while this is false, including the runtime's call-duration guard — nothing in this section changes behaviour until it is turned on. |
| `RATE_LIMIT_FAIL_OPEN` | `True` | No | On a Redis outage: allow and log at ERROR (`True`), or 503 with `Retry-After` (`False`). |
| `RATE_LIMIT_IP_SALT` | `""` | Yes, if `RATE_LIMIT_ENABLED=true` | Salt for hashing client IPs before they touch Redis or logs. Must not reuse `SECRET_KEY`. Startup aborts if enabled with this empty. |
| `TRUST_PROXY_HEADERS` | `False` | No | Parse `X-Forwarded-For` for client IP resolution. Defaults false so a misconfigured deployment fails closed to the proxy's own IP rather than open to a spoofed header. |
| `TRUSTED_PROXY_HOPS` | `1` | No | Hops between the client and this service. **Measure against the real deployment before changing** — there are two proxy hops in front of `apps/api` (nginx, then the Next.js rewrite proxy); guessing wrong collapses every per-IP limit to one global counter. See the plan's §7. |
| `RATE_LIMIT_IP_ALLOWLIST` | `""` | No | Comma-separated IPs/CIDRs (v4 and v6) exempt from per-IP limits only — never from org-scoped limits. A malformed entry aborts startup. |
| `RATE_LIMIT_SCOPE_STALE_SECONDS` | `900` | No | Reaper window for per-IP concurrency slots. Kept independent of and shorter than the org reaper (`MAX_CALL_DURATION_CEILING_SECONDS + 300`) — see the plan's S3b. |
| `SIGNUP_ORGS_PER_IP_PER_HOUR` | `2` | No | Successful org creations per IP per hour. |
| `SIGNUP_ORGS_PER_IP_PER_DAY` | `5` | No | Successful org creations per IP per day. |
| `SIGNUP_ATTEMPTS_PER_IP_PER_HOUR` | `10` | No | `/users/signup` attempts per IP per hour, regardless of outcome. |
| `AUTH_ATTEMPTS_PER_IP_PER_MINUTE` | `10` | No | Shared budget for `/login`, `/forgot-password`, `/reset-password`, `/users/check/{email}`. |
| `RESET_MAILS_PER_EMAIL_PER_HOUR` | `3` | No | Password-reset emails per *target* email address per hour (not per requester IP). |
| `MAX_CONCURRENT_CALLS_PER_IP` | `5` | No | Concurrent web calls per client IP. |
| `ORG_DAILY_CALL_SECONDS` | `14400` (4h) | No | Default daily call-seconds quota per org. Overridable per org via `Organizations.daily_call_seconds`. |
| `MAX_CALL_DURATION_SECONDS` | `600` | No | Default single-call duration cap, applied by the runtime only when `RATE_LIMIT_ENABLED=true`. Overridable per org via `Organizations.max_call_duration_seconds`, and per agent via `behaviour.call_timeout_seconds`. |
| `MAX_CALL_DURATION_CEILING_SECONDS` | `1800` | No | Unconditional ceiling *relative to the overrides above* — applied server-side, so no override can exceed it. Still subject to `RATE_LIMIT_ENABLED`. |
| `RUNTIME_SESSION_SECRET` | `""` | Yes, once Layer 2b ships | HMAC key for signing/verifying the runtime WebSocket admission token. Read by both `apps/api` (signs) and `apps/runtime` (verifies) — must be a dedicated key, not `SECRET_KEY`. |

## Object storage

MinIO holds call recordings, transcripts, campaign source CSVs, and knowledge-base PDFs.

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `MINIO_ENDPOINT` | `localhost:9000` | No | Host and port of the MinIO S3 API. Compose overrides it to `minio:9000`. |
| `MINIO_ACCESS_KEY` | `minioadmin` | No | Access key used by the API, the ARQ worker, and the runtime. |
| `MINIO_SECRET_KEY` | `minioadmin123` | No | Secret key. |
| `MINIO_SECURE` | `false` | No | Whether to use TLS to reach MinIO. Compose pins it to `false` inside the stack. |
| `MINIO_BUCKET` | `voicera-calls` | No | Bucket for call artifacts and knowledge-base objects. |

`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` configure the MinIO server; `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` are what the applications authenticate with. `.env.example` ships them as the same pair, so changing only one half locks the applications out.

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
| `MINIO_ENDPOINT` | `localhost:9000` | `minio:9000` | Same reason. |
| `MINIO_SECURE` | `false` | `false` | Pinned explicitly on `api` and `arq-worker`. |
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
