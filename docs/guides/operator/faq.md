---
title: FAQ
description: Common questions about running VoicEra.
---

## Where is the dashboard?

The core stack does not include one. VoicEra is API-first: `http://localhost:8000/docs` gives you an interactive console for every endpoint.

On `http://localhost:3000`, started with the rest of the stack. It covers agents, numbers, campaigns, knowledge documents, call history, and per-call latency. Its container runs the Next.js development server, so build it properly before exposing it. See [Dashboard](../../developer/frontend/overview) and [Operating via the API](../../api-reference/recipes).

## Why is the database on port 27018?

The container listens on `27017`; the host mapping is `27018` so it cannot collide with a MongoDB you already run locally. From your machine use `27018`; inside the Compose network services use `mongodb:27017`.

It is FerretDB — the MongoDB wire protocol on top of PostgreSQL — not MongoDB. See [Data store](../../developer/reference/data-store).

## Do I need a GPU?

Not with cloud model providers. The core stack runs on 2 CPU cores and 4 GB of RAM.

A GPU is only needed to self-host models with the [model server](../../developer/model-server/overview).

## Can I use only OpenAI?

Yes. `openai` registers speech-to-text, text-to-speech, and a language model, so one credential covers all three. `google` and `sarvam` do the same.

Mixing is common — Deepgram for STT, Cartesia for TTS, OpenAI for the LLM. The choice is per agent.

## Why are my provider dropdowns or catalogs empty?

Catalogs filter to providers you have stored credentials for. Store them first:

```bash
curl -X POST http://localhost:8000/api/v1/auth \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"provider": "openai", "auth": {"api_key": "sk-..."}}'

curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/auth/configured
```

## Why did my campaign pause itself?

The circuit breaker tripped — by default, more than 50% of calls failing within a 300-second window, over a minimum of 5 calls. It exists so a broken agent burns a handful of calls instead of the whole list.

Find out why the calls failed, fix it, then `POST /campaign/{id}/resume`. See [Troubleshooting campaigns](../troubleshooting/campaigns).

## Why does my browser test call have no transcript?

Browser sessions do produce transcripts and recordings — the runtime registers a `call_type: web` call log on connect. If one is missing, check the runtime log for `Registered web call call_id=` and confirm MinIO is reachable.

## Do I need a public URL?

Only for real phone calls. Your telephony provider fetches `/answer` over HTTPS and opens a WSS connection for audio — both inbound, so the runtime must be publicly reachable.

For evaluation, a `websocket` agent needs no public URL and no telephony account. See [Public voice URLs](../../guides/deployment/public-voice-urls).

## My agents stopped answering after I changed a setting. Why?

Almost certainly `VOICE_SERVER_BASE_URL`. The answer URL is baked into the provider application when an agent is **created**, so changing it later does not update existing agents — your provider keeps calling the old address, and nothing reaches VoicEra to log.

`PATCH` each affected agent to re-provision, or recreate it.

## How do I change a default password?

Edit `.env` and recreate the affected containers. Change `MONGODB_PASSWORD`, `MINIO_ROOT_PASSWORD`, and `REDIS_PASSWORD` at minimum.

<Warning>
Changing `MONGODB_PASSWORD` after the volume exists does not update the PostgreSQL user — the same credentials serve both layers. Set it before the first start, or change it inside Postgres too.
</Warning>

See [Security hardening](../../guides/deployment/security-hardening).

## What happens if I lose PROVIDER_AUTH_ENCRYPTION_KEY?

Every stored provider credential becomes permanently undecryptable. There is no recovery path and no re-encryption tool — each organisation must re-enter every provider key.

Back it up with the same care as the database, and store it alongside your backups.

## Is there a default login?

No. The first `POST /users/signup` creates the user, an organisation, and a `super_admin` membership. Whoever signs up first owns the deployment, so do it immediately after starting.

## How many calls can run at once?

`DEFAULT_ORG_CONCURRENCY_LIMIT` caps simultaneous calls per organisation, default `10`. Campaigns can set a lower `max_concurrency`.

In practice your telephony account's channel limit or your model vendor's rate limits usually bind first. See [Call concurrency](../../developer/reference/call-concurrency).

## Can I scale the services?

The API, runtime, and ARQ worker scale horizontally. The runtime needs session affinity, since each live call holds one WebSocket.

<Warning>
The campaign orchestrator must run as **exactly one** replica. Its state is in-memory and it uses Redis pub/sub, which fans out to every subscriber — two replicas would dial each campaign at twice its configured rate.
</Warning>

See [Production deployment](../../guides/deployment/production).

## Does VoicEra switch language mid-call?

No. An agent declares a primary language and optional secondary ones, but nothing switches during a call. Choose a provider whose model covers the languages you expect, or run separate numbers per language.

## Where are recordings stored?

MinIO, under `voicera-calls/{org_id}/{call_id}/`. Fetch them through the authenticated API rather than the bucket:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/calls/$CALL_ID/recording -o recording.wav
```

Nothing expires automatically — set a retention policy.

## How do I back up?

Three stores together: PostgreSQL (via `pg_dump`), MinIO, and the Chroma volume. Redis is ephemeral. Store `PROVIDER_AUTH_ENCRYPTION_KEY` with the backup — credentials are useless without it.

<Warning>
`docker compose down -v` deletes all four volumes at once, irreversibly.
</Warning>

See [Daily operations](operations).

## Is there a CI pipeline?

No. There is no `.github/` directory. Run the test suites yourself before opening a pull request — see [Testing](../../developer/guides/testing).

## Related

* [Common issues](../troubleshooting/common-issues)
* [Operating via the API](../../api-reference/recipes)
* [Glossary](../concepts/glossary)
