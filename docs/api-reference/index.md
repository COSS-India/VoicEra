---
title: API Reference
description: Every HTTP and WebSocket surface VoicEra exposes.
---

The complete VoicEra API: 71 REST routes across twelve routers, plus the realtime media WebSocket. Every page here was extracted from the routers and verified against them.

<Tip>
A running API serves an **interactive console** at `http://localhost:8000/docs`, generated from the same code. Use it to fire real requests; use these pages to learn what a route does and how it behaves.
</Tip>

<Note>
There is no official Node.js, Python, or other client SDK. Every example on this site is a raw `curl` request or, for the WebSocket, a standard library client (`WebSocket` in the browser, [`websockets`](https://websockets.readthedocs.io/) in Python) — see [Recipes](/docs/api-reference/recipes) for REST and [WebSocket API](/docs/api-reference/websocket-api#connecting) for the socket. `GET /openapi.json` on a running API is a valid input to any OpenAPI client generator if you want to build your own typed client.
</Note>

## Start here

| Page | Covers |
| --- | --- |
| [Introduction](/docs/api-reference/overview) | Base URL, versioning, request and response conventions |
| [Authentication](/docs/api-reference/authentication) | JWTs, `X-API-Key`, roles, organisation scoping |
| [Errors](/docs/api-reference/errors) | Status codes and error shapes |
| [Endpoints cheatsheet](/docs/api-reference/endpoints-cheatsheet) | Every route across all three services, one page |

## Endpoints by resource

| Page | Routes | What it covers |
| --- | --- | --- |
| [Agents](/docs/api-reference/agents) | 6 | Create, read, update, delete voice agents |
| [Calls](/docs/api-reference/calls) | 9 | Outbound, inbound, web calls; recordings and transcripts |
| [Campaigns](/docs/api-reference/campaigns) | 14 | CSV upload, scheduling, start/pause/resume, progress, reports |
| [Phone numbers](/docs/api-reference/phone-numbers) | 5 | Number inventory, attaching to agents |
| [Knowledge and RAG](/docs/api-reference/knowledge-and-rag) | 4 | Document upload and retrieval |
| [Configuration catalogs](/docs/api-reference/configuration) | 9 | Which providers exist and what each accepts |
| [Provider credentials](/docs/api-reference/provider-auth) | 6 | Storing encrypted API keys |
| [Users and organisations](/docs/api-reference/users-and-orgs) | 15 | Signup, login, membership, roles, bot tokens |

## Realtime

* [**WebSocket API**](/docs/api-reference/websocket-api) — `WS /agent/{org_id}/{agent_id}` in both modes: telephony frame serializers at 8 kHz, browser protobuf/RTVI at 16 kHz.

## Conventions on every page

Each endpoint lists its **method and path**, the **auth** it requires, its **request** fields, its **response** shape, and the **errors** it can return. Paths already include the `/api/v1` prefix.

## Related

* [Recipes](/docs/api-reference/recipes) — task-shaped recipes built on these routes
* [Connecting a client](/docs/developer/clients) — choosing a surface
* [Data model](/docs/developer/reference/data-model) — the documents behind these routes
