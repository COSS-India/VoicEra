---
title: API overview
description: Base URL, versioning, request and response conventions.
---

The VoicEra API is a JSON REST API served by the `api` container on port `8000`. Everything the platform does — users, agents, credentials, numbers, calls, campaigns, documents — is available through it. There is no private admin surface.

<Note>
There is no official Node.js, Python, or other client SDK. Integrate with plain HTTP — every example in this reference is `curl`. `GET /openapi.json` on a running API works with any OpenAPI client generator if you want a typed client of your own.
</Note>

<Tip>
A running API serves an **interactive console** at `http://localhost:8000/docs` and ReDoc at `/redoc`, generated from the same routers as these pages. Use it to try requests against a real token; use these pages to understand what a route is for and how it behaves.
</Tip>

Every router is mounted under `settings.API_V1_PREFIX`, which defaults to `/api/v1` (`apps/api/app/config.py`). Paths on this page already include it.

Two routes are declared on the app itself in `apps/api/app/main.py` and are **not** prefixed:

| Method | Path | Auth | Response |
| --- | --- | --- | --- |
| GET | `/` | public | `{"message": "Welcome to …", "version": "…", "docs": "/docs"}` |
| GET | `/health` | public | `{"status": "ok" \| "degraded", "database": "up" \| "down"}` |

`/health` pings FerretDB. It always returns `200`; read the body, not the status code.

## Request format

Send `Content-Type: application/json` on every request with a body. Two routes take `multipart/form-data` instead, because they carry a file: `POST /api/v1/campaign/upload` and `POST /api/v1/knowledge/upload`.

## Browse by resource

| Page | Covers |
| --- | --- |
| [Agents](agents) | Create and manage voice agents |
| [Calls](calls) | Place calls, register them, fetch artifacts |
| [Campaigns](campaigns) | Outbound campaigns end to end |
| [Phone numbers](phone-numbers) | Number inventory and agent attachment |
| [Knowledge and RAG](knowledge-and-rag) | Documents and retrieval |
| [Configuration catalogs](configuration) | Which providers exist and what they accept |
| [Provider credentials](provider-auth) | Storing encrypted API keys |
| [Users and organisations](users-and-orgs) | Signup, login, membership, roles |

Prefer one flat list? See the [Endpoints cheatsheet](endpoints-cheatsheet).

## Related

* [Authentication](authentication) — tokens, headers, and roles
* [Errors](errors) — status codes and error shapes
* [WebSocket API](websocket-api) — the media protocol
* [Recipes](recipes) — task-shaped recipes
