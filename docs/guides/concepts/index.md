---
title: Core concepts
description: How VoicEra works — the ideas behind the code, in dependency order.
---

The engineering model behind VoicEra. These pages explain *why* the system is shaped the way it is; the [Reference](../../api-reference/overview.md) section gives the exact contracts.

<Note>
Reading in order works, but is not required. If you only have ten minutes, read [Architecture](architecture.md) and [Voice pipeline](voice-pipeline.md) — everything else builds on those two.
</Note>

## Start here

| Page | What it answers |
| --- | --- |
| [Architecture](architecture.md) | What the containers are and how they fit together. |
| [Voice pipeline](voice-pipeline.md) | What happens between a caller speaking and the agent replying. |
| [Data flow](data-flow.md) | What moves where, for each call scenario. |

## The domain

| Page | What it answers |
| --- | --- |
| [Agents and agent categories](agents.md) | What an agent is, and why `telephony` and `websocket` behave differently. |
| [Calls and call artifacts](calls.md) | Call types, statuses, and where recordings and transcripts land. |
| [Campaigns](campaigns.md) | CSV-driven outbound at volume: batches, retries, circuit breakers. |
| [Knowledge base (RAG)](knowledge-base-rag.md) | Grounding answers in your own documents. |

## Providers and telephony

| Page | What it answers |
| --- | --- |
| [Telephony model](telephony-model.md) | One `/answer` webhook serving multiple carriers. |

<Note>
How providers plug in, how credentials are encrypted, how organisations and roles are scoped, why calls get queued or refused under concurrency limits, and why the data store speaks the MongoDB wire protocol — these are implementation details for people extending or operating the system, not product concepts. They live in the Developer tab's [System architecture](../../developer/reference/provider-registry.md) group.
</Note>

## Platform

| Page | What it answers |
| --- | --- |
| [Glossary](glossary.md) | Every term this documentation assumes. |

## Related

* [Services](../../developer/services/index.md) — the same system, from the operator's side
* [System architecture](../../developer/reference/provider-registry.md) — providers, multi-tenancy, and the data store, for the people extending or running the system
* [Repository layout](../../developer/guides/repository-layout.md) — where each concept lives in code
