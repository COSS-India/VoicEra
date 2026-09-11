---
title: API Reference
description: Every HTTP and WebSocket surface VoicEra exposes.
---

The complete VoicEra API: 71 REST routes across twelve routers, plus the realtime media WebSocket. Every page here was extracted from the routers and verified against them.

<Tip>
A running API serves an **interactive console** at `http://localhost:8000/docs`, generated from the same code. Use it to fire real requests; use these pages to learn what a route does and how it behaves.
</Tip>

<Note>
There is no official Node.js, Python, or other client SDK. Every example on this site is a raw `curl` request or, for the WebSocket, a standard library client (`WebSocket` in the browser, [`websockets`](https://websockets.readthedocs.io/) in Python) — see [Recipes](recipes) for REST and [WebSocket API](websocket-api#connecting) for the socket. `GET /openapi.json` on a running API is a valid input to any OpenAPI client generator if you want to build your own typed client.
</Note>

## Start here

| Page | Covers |
| --- | --- |
| [Introduction](overview) | Base URL, versioning, request and response conventions |
| [Authentication](authentication) | JWTs, `X-API-Key`, roles, organisation scoping |
| [Errors](errors) | Status codes and error shapes |
| [Endpoints cheatsheet](endpoints-cheatsheet) | Every route across all three services, one page |

## Endpoints by resource

| Page | Routes | What it covers |
| --- | --- | --- |
| [Agents](agents) | 6 | Create, read, update, delete voice agents |
| [Calls](calls) | 9 | Outbound, inbound, web calls; recordings and transcripts |
| [Campaigns](campaigns) | 14 | CSV upload, scheduling, start/pause/resume, progress, reports |
| [Phone numbers](phone-numbers) | 5 | Number inventory, attaching to agents |
| [Knowledge and RAG](knowledge-and-rag) | 4 | Document upload and retrieval |
| [Configuration catalogs](configuration) | 9 | Which providers exist and what each accepts |
| [Provider credentials](provider-auth) | 6 | Storing encrypted API keys |
| [Users and organisations](users-and-orgs) | 15 | Signup, login, membership, roles, bot tokens |

## Realtime

* [**WebSocket API**](websocket-api) — `WS /agent/{org_id}/{agent_id}` in both modes: telephony frame serializers at 8 kHz, browser protobuf/RTVI at 16 kHz.

## Conventions on every page

Each endpoint lists its **method and path**, the **auth** it requires, its **request** fields, its **response** shape, and the **errors** it can return. Paths already include the `/api/v1` prefix.

## Related

* [Recipes](recipes) — task-shaped recipes built on these routes
* [Connecting a client](../developer/clients/index) — choosing a surface
* [Data model](../developer/reference/data-model) — the documents behind these routes
