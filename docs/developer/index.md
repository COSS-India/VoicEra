---
title: Developer
description: Build on VoicEra, extend it, or run it on your own infrastructure.
---

How VoicEra is put together, and how to change it. If you want to *use* the API rather than modify the system, the [API Reference](../api-reference/overview) tab is the shorter path.

## Where to start

| If you want to… | Start here |
| --- | --- |
| Run the stack from source | [Local setup](guides/local-setup) |
| Understand the moving parts | [Services overview](services/index) |
| Add a new STT, TTS, or LLM vendor | [Adding an AI provider](guides/adding-a-provider) |
| Add a new telephony carrier | [Adding a telephony provider](guides/adding-a-telephony-provider) |
| Run models on your own GPUs | [Model server](model-server/index) |
| Connect something to VoicEra | [Connecting a client](clients/index) |
| Look up a variable or a port | [Configuration reference](reference/environment-variables) |

## Services

Ten containers, five Python packages. `apps/api` alone runs as three containers off one image.

* [**Overview**](services/index) — containers, ports, start-up order, who talks to whom
* [**API**](services/api) — routers, service layer, persistence, lifecycle
* [**Runtime**](services/runtime) — the answer webhook and the Pipecat pipeline
* [**Providers**](services/providers) — the registry that makes vendors pluggable
* [**Telephony**](services/telephony) — carrier clients, answer XML, frame serializers
* [**Workers and orchestrator**](services/workers) — ARQ jobs and campaign scheduling

## Model server

Optional. Run STT, TTS, and LLM on your own hardware behind one gateway on `:8100`.

* [**Model server**](model-server/index) — the section index
* [**Slots and models**](model-server/slots-and-models) — swap a model with one line
* [**Running on GPUs**](model-server/gpu-operations) — device selection, MPS, caching

## Contributing

* [**Local setup**](guides/local-setup) · [**Repository layout**](guides/repository-layout)
* [**Adding an AI provider**](guides/adding-a-provider) · [**Adding a telephony provider**](guides/adding-a-telephony-provider)
* [**Testing**](guides/testing) — the five suites and what each protects
* [**Contributing**](guides/contributing-guide) — branches, commits, pull requests

<Note>
There is no CI. Run the test suites yourself before opening a pull request — [Testing](guides/testing) lists all five and what each needs.
</Note>

## Configuration reference

* [**Environment variables**](reference/environment-variables) — the single root `.env`, annotated
* [**Ports and defaults**](reference/ports-and-defaults) — published versus internal
* [**Data model**](reference/data-model) — collections, fields, enums, indexes
* [**Agent configuration**](reference/agent-configuration) — the full `config` contract

## Dashboard

<Note>
The Next.js dashboard is part of the Compose stack, on port 3000. Its container runs the Next.js development server, so build it properly before exposing it. See [Dashboard](frontend/index).
</Note>
