---
title: Model server
description: Run STT, TTS, and LLM on your own GPUs behind one gateway.
---

An optional, self-contained subsystem for running speech and language models on your own hardware. One gateway on `:8100` fronts three slots — STT, TTS, LLM — and each slot runs whichever model you selected, without the gateway knowing which one.

<Note>
The model server is **optional**. VoicEra runs fine against cloud providers alone. Deploy this when data residency, per-minute cost, or Indic-language coverage makes self-hosting worth the GPUs.
</Note>

## Start here

| Page | What it answers |
| --- | --- |
| [Overview](/docs/developer/model-server/overview) | What it is, what it replaces, and its current state. |
| [Slots and models](/docs/developer/model-server/slots-and-models) | The slot/model split, and switching models with one line. |
| [Gateway API](/docs/developer/model-server/gateway-api) | Every endpoint, including `WS /v1/asr/ws`. |

## The models

| Page | Covers |
| --- | --- |
| [STT models](/docs/developer/model-server/stt-models) | `indic-conformer`, `indic-transcribe`, and partial transcripts versus streaming. |
| [TTS models](/docs/developer/model-server/tts-models) | `indic-parler`, `orpheus`, `indic-mio`, `rumik-oss-1`, `higgs-tts-3`, `maya2-native`, and audio format negotiation. |
| [LLM models](/docs/developer/model-server/llm-models) | `qwen3.5-4b` and the model-id agreement across files. |

## Operating it

| Page | Covers |
| --- | --- |
| [Adding a model](/docs/developer/model-server/adding-a-model) | The container contract, and the two steps to add one. |
| [Running on GPUs](/docs/developer/model-server/gpu-operations) | Device selection, MPS, shared HuggingFace cache, disk. |

## Honest status

<Note>
Two gaps are documented rather than hidden. The LLM slot has not yet been run on real hardware, and a full call routed from the voice runtime through a self-hosted model has not been verified end to end. Both are called out on the pages concerned.
</Note>

## Related

* [Self-hosted models](/docs/guides/deployment/self-hosted-models) — wiring the model server to the runtime
* [Provider registry](/docs/developer/reference/provider-registry) — how agents select a provider
