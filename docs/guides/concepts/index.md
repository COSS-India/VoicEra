---
title: Core concepts
description: How VoicEra works — the ideas behind the code, in dependency order.
---

The engineering model behind VoicEra. These pages explain *why* the system is shaped the way it is; the [Reference](/docs/api-reference/overview) section gives the exact contracts.

<Note>
Reading in order works, but is not required. If you only have ten minutes, read [Architecture](/docs/guides/concepts/architecture) and [Voice pipeline](/docs/guides/concepts/voice-pipeline) — everything else builds on those two.
</Note>

## Start here

| Page | What it answers |
| --- | --- |
| [Architecture](/docs/guides/concepts/architecture) | What the containers are and how they fit together. |
| [Voice pipeline](/docs/guides/concepts/voice-pipeline) | What happens between a caller speaking and the agent replying. |
| [Data flow](/docs/guides/concepts/data-flow) | What moves where, for each call scenario. |

## The domain

| Page | What it answers |
| --- | --- |
| [Agents and agent categories](/docs/guides/concepts/agents) | What an agent is, and why `telephony` and `websocket` behave differently. |
| [Calls and call artifacts](/docs/guides/concepts/calls) | Call types, statuses, and where recordings and transcripts land. |
| [Campaigns](/docs/guides/concepts/campaigns) | CSV-driven outbound at volume: batches, retries, circuit breakers. |
| [Knowledge base (RAG)](/docs/guides/concepts/knowledge-base-rag) | Grounding answers in your own documents. |

## Providers and telephony

| Page | What it answers |
| --- | --- |
| [Telephony model](telephony-model) | One `/answer` webhook serving Vobiz, Plivo, VI, and Go2Market. |

<Note>
How providers plug in, how credentials are encrypted, how organisations and roles are scoped, why calls get queued or refused under concurrency limits, and why the data store speaks the MongoDB wire protocol — these are implementation details for people extending or operating the system, not product concepts. They live in the Developer tab's [System architecture](/docs/developer/reference/provider-registry) group.
</Note>

## Platform

| Page | What it answers |
| --- | --- |
| [Glossary](/docs/guides/concepts/glossary) | Every term this documentation assumes. |

## Related

* [Services](/docs/developer/services) — the same system, from the operator's side
* [System architecture](/docs/developer/reference/provider-registry) — providers, multi-tenancy, and the data store, for the people extending or running the system
* [Repository layout](/docs/developer/guides/repository-layout) — where each concept lives in code
