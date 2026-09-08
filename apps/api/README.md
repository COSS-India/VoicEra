# VoicEra API

> FastAPI backend — auth, agents, provider credentials, phone numbers, calls, campaigns, and the knowledge base.

[![Port](https://img.shields.io/badge/port-8000-blue.svg)](http://localhost:8000/docs)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![FerretDB](https://img.shields.io/badge/FerretDB-2.7-042E5B.svg)](https://www.ferretdb.com/)

Auth and org membership are backed by [FerretDB](https://www.ferretdb.com/) — the MongoDB wire protocol over PostgreSQL.

> [!NOTE]
> This package runs as **three** containers off one image: `api`, `arq-worker`, and `campaign-orchestrator`. They differ only in their `command`.

## Quick start (Docker)

Deployment files live at the **repo root**: `docker-compose.yaml`
plus helper scripts under `scripts/`.

From the repository root:

```bash
./scripts/start_docker.sh
```

Stop with:

```bash
./scripts/stop_services.sh
```

- API: http://localhost:8000 (override with `API_HOST_PORT`)
- OpenAPI docs: http://localhost:8000/docs
- FerretDB (Mongo wire): `localhost:27018` (override with `FERRETDB_HOST_PORT`)

Root `.env` is created/updated by `start_docker.sh` (secrets generated if missing).
Copy [`.env.example`](../../.env.example) to the repo root — there is no per-app `.env`.

## Local development (API process on the host)

1. From repo root, start only the DB layer:

```bash
docker compose -f docker-compose.yaml up postgres ferretdb
```

2. In `apps/api`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# from repo root: cp .env.example .env  (MONGODB_HOST=localhost, MONGODB_PORT=27018)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Auth endpoints (`/api/v1`)

| Method | Path | Auth |
|--------|------|------|
| POST | `/users/signup` | public → JWT (`super_admin` of new org) |
| POST | `/users/login` | public → JWT |
| POST | `/users/bot/token` | `X-API-Key: INTERNAL_API_KEY` — body `{ "org_id" }` → org-scoped JWT (`admin`) |
| POST | `/users/switch-organisation` | Bearer (persists default org for next login) |
| GET | `/users/organisations` | Bearer |
| GET | `/users/me` | Bearer |
| GET | `/users/check/{email}` | public |
| GET | `/users/{email}` | Bearer (self) |
| POST | `/users/forgot-password` | public |
| POST | `/users/reset-password` | public |
| POST | `/members/invite` | Bearer (`admin` or `super_admin`) |
| GET | `/members/{org_id}` | Bearer (member of org) |
| POST | `/members/assign-admin` | Bearer (`super_admin`) |
| POST | `/members/remove` | Bearer (`super_admin`) |
| DELETE | `/organisations/{org_id}` | Bearer (`super_admin`, active org) |

Bot/orchestrator: `POST /users/bot/token` with internal key + `org_id` from call/agent context. Use returned `access_token` as `Authorization: Bearer` for other APIs (including `/auth/*`). Unknown `org_id` → 404.

## Configuration catalogs (`/api/v1`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/configuration/stt` | Bearer (optional `languages` AND filter) |
| GET | `/configuration/tts` | Bearer (optional `languages`) |
| GET | `/configuration/llm` | Bearer |
| GET | `/configuration/telephony` | Bearer |
| GET | `/configuration/stt/setting/{provider}` | Bearer |
| GET | `/configuration/tts/setting/{provider}` | Bearer |
| GET | `/configuration/llm/setting/{provider}` | Bearer |
| GET | `/configuration/telephony/setting/{provider}` | Bearer |

## Provider auth (`/api/v1`)

Credentials are **provider-level** (one key set shared across STT/TTS/LLM for that provider).
Only **secret** fields are stored in `ProviderAuth`; the whole `auth` object is Fernet-encrypted at rest (`PROVIDER_AUTH_ENCRYPTION_KEY`).

| Method | Path | Auth |
|--------|------|------|
| GET | `/auth/catalog` | Bearer — all provider auth schemas |
| GET | `/auth/catalog/{provider}` | Bearer — one provider schema |
| GET | `/auth/configured` | Bearer — provider ids with stored auth |
| POST | `/auth` | Bearer (`admin` or `super_admin`) — upsert `{provider, auth}` (secrets only) |
| GET | `/auth/{provider}` | Bearer — stored auth (members see masked secrets) |
| DELETE | `/auth/{provider}` | Bearer (`admin` or `super_admin`) |

Collections: `Organizations`, `Users`, `Memberships`, `ProviderAuth`, `Agents`,
`PhoneNumbers`, `CallLogs`, `Campaigns`, `QueuedRuns`, `KnowledgeDocuments`
(roles: `super_admin`, `admin`, `member`). Created and indexed idempotently on
startup by `app/database_init.py`. See
[Data model](../../docs/developer/reference/data-model.md).

## Agents (`/api/v1`)

Agents store typed behaviour + AI model configs (secret-free). For
**telephony** agents the API automatically creates a provider application
using org credentials from `ProviderAuth` and stores the attachment on the
agent document. **WebSocket** agents skip telephony provisioning.

Set `VOICE_SERVER_BASE_URL` (e.g. `https://voice.example.com`) before creating
telephony agents. Answer and hangup use the same URL:

- `{VOICE_SERVER_BASE_URL}/answer?agent_id={agent_id}&org_id={org_id}`

| Method | Path | Auth |
|--------|------|------|
| POST | `/agents` | Bearer (any org member) — create; `created_by` = JWT email |
| GET | `/agents` | Bearer — list agents in active org |
| GET | `/agents/by-phone/{phone_number}` | `X-API-Key` — resolve agent by linked number (runtime) |
| GET | `/agents/{agent_id}` | Bearer — get one (same org) |
| PATCH | `/agents/{agent_id}` | Bearer (any org member) — partial update |
| DELETE | `/agents/{agent_id}` | Bearer (`admin` or `super_admin`) |

**Create telephony agent** — `agent_category: "telephony"` requires
`telephony_provider` (a provider id registered in `apps.telephony`; see
`GET /configuration/telephony`) and configured org auth via
`POST /auth`. On create the API provisions a provider application and returns
`telephony.application_id`. On delete (or when switching away from telephony /
changing provider on PATCH) any attached phone is unlinked/detached and the
application is removed.

**Create websocket agent** — `agent_category: "websocket"`; do not send
`telephony_provider`. `telephony` stays `null`.

Example telephony create body:

```json
{
  "name": "Support Agent",
  "agent_category": "telephony",
  "telephony_provider": "vobiz",
  "config": { "...": "..." }
}
```

`config.models` must include `stt_config`, `tts_config`, and `llm_config` with
a registered `provider` and non-secret settings only (no API keys). Use
`GET /configuration/*` and `GET /auth/*` for form catalogs and credentials.

## Phone numbers (`/api/v1`)

Org inventory of DIDs plus attach/detach to telephony agents. Attach/detach
also link/unlink the number to the agent's provider application via
`apps.telephony`.

| Method | Path | Auth |
|--------|------|------|
| GET | `/phone-numbers` | Bearer — list org inventory |
| GET | `/phone-numbers/agent/{agent_id}` | Bearer — number attached to agent |
| POST | `/phone-numbers/attach` | Bearer — add to inventory; with `agent_id` also provider-link + set `Agents.linked_phone_number` |
| DELETE | `/phone-numbers/detach` | Bearer — provider-unlink + clear agent association (keeps inventory row) |
| GET | `/phone-numbers/providers/{provider}/inventory` | Bearer — list numbers on the org provider account |

Attach body:

```json
{
  "phone_number": "+15551234567",
  "provider": "vobiz",
  "agent_id": "optional-agent-uuid"
}
```

Omit `agent_id` to import a number into org inventory only (no provider link).

## Calls (`/api/v1`)

Call logs for inbound, outbound, and web calls, plus artifact proxying from MinIO.

| Method | Path | Auth |
|--------|------|------|
| POST | `/calls/outbound` | Bearer — place an outbound call (takes a concurrency slot) |
| POST | `/calls/inbound` | `X-API-Key` — register an inbound call (idempotent per provider SID) |
| POST | `/calls/web` | Bearer — register a browser websocket session (`call_type: web`) |
| PATCH | `/calls/by-provider-sid/{provider_call_sid}` | `X-API-Key` — reconcile by provider id |
| PATCH | `/calls/{call_id}` | `X-API-Key` — runtime posts outcome, duration, artifact URIs |
| GET | `/calls/{call_id}` | Bearer |
| GET | `/calls/org/{org_id}` | Bearer — paginated list |
| GET | `/calls/{call_id}/recording` | Bearer — proxied from MinIO |
| GET | `/calls/{call_id}/transcript` | Bearer — proxied from MinIO |

Artifacts live at `voicera-calls/{org_id}/{call_id}/{recording.wav,transcript.txt}`.
The CallLog stores `minio://` URIs; clients always fetch through these routes.

## Campaigns (`/api/v1`)

CSV-driven outbound campaigns. Scheduling runs in the `campaign-orchestrator`
container and batches execute on the ARQ worker.

| Method | Path | Auth |
|--------|------|------|
| POST | `/campaign/upload` | Bearer — upload the contact CSV |
| POST | `/campaign/create` | Bearer |
| GET | `/campaign/` | Bearer |
| GET | `/campaign/{campaign_id}` | Bearer |
| PATCH | `/campaign/{campaign_id}` | Bearer |
| POST | `/campaign/{campaign_id}/start` | Bearer |
| POST | `/campaign/{campaign_id}/pause` | Bearer |
| POST | `/campaign/{campaign_id}/resume` | Bearer — from `paused` only |
| POST | `/campaign/{campaign_id}/redial` | Bearer |
| GET | `/campaign/{campaign_id}/runs` | Bearer |
| GET | `/campaign/{campaign_id}/progress` | Bearer |
| GET | `/campaign/{campaign_id}/report` | Bearer |
| GET | `/campaign/{campaign_id}/source-download-url` | Bearer |
| POST | `/campaign/internal/call-status` | `X-API-Key` — terminal call status from the runtime |

`max_concurrency`, `schedule_config`, and `circuit_breaker` are top-level on the
request models but stored nested under `orchestrator_metadata`.

## Knowledge base (`/api/v1`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/knowledge` | Bearer — list org documents |
| POST | `/knowledge/upload` | Bearer — upload a PDF; ingests, chunks, and embeds |
| DELETE | `/knowledge/{document_id}` | Bearer |
| POST | `/rag/retrieve` | `X-API-Key` — top-k chunk retrieval for the runtime |

Requires `KB_EMBEDDING_API_KEY` and `KB_EMBEDDING_MODEL`. PDF only.

## Languages (`/api/v1`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/languages` | Bearer — canonical language ids and labels |

Service-to-service calls use the `X-API-Key` header with `INTERNAL_API_KEY` (see `POST /users/bot/token`).

---

Full documentation: [API service](../../docs/developer/services/api.md) · [REST API reference](../../docs/api-reference/overview.md) · [Data model](../../docs/developer/reference/data-model.md)
