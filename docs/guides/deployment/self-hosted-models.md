---
title: Self-hosted models
description: Pointing VoicEra at your own model server instead of cloud providers.
---

Run speech and language models on your own GPUs so audio and text never leave your network. This page covers deploying the model server and wiring it to the runtime.

<Note>
**This path is not verified end to end.** `model-server/README.md` states plainly that a real call through the voice server pointed at the gateway has **not been tested**, and that the LLM slot "has never been built or started". STT and TTS have been verified standalone on an H200; the integration has not. Budget time for debugging, and do not put this in front of callers without testing it yourself.
</Note>

## When to self-host

| Reason | Detail |
| --- | --- |
| **Data residency** | Call audio and transcripts never reach a third-party API |
| **Cost at volume** | Fixed hardware cost instead of per-minute billing |
| **Language coverage** | Indic models that cloud vendors serve poorly or not at all |
| **Offline operation** | No dependency on external availability |

Against: you need GPUs, the images are large, and cold starts are slow. Mixing is common — self-host speech, use a cloud LLM, or the reverse.

## Deploy the model server

From the repository root:

```bash
STT_MODEL=indic-conformer TTS_MODEL=indic-parler make model-server-setup
```

The gateway comes up on `:8100`; the model slots stay internal on `8001`, `8002`, `8003`. Check it:

```bash
curl -s localhost:8100/health
curl -s localhost:8100/v1/models
```

Full detail in [Model server overview](../../developer/model-server/overview) and [Slots and models](../../developer/model-server/slots-and-models).

<Tip>
Weights are **not** in the repository. `stt/indic-conformer/models/IndicConformer.nemo` and `tts/indic-parler/checkpoints/` are gitignored, and `ai4bharat/indic-parler-tts` is a **gated** HuggingFace repo — you need a token with access, or a pre-populated cache. Build one image at a time on a tight disk; parallel builds double peak usage at the export stage, which is where they fail.
</Tip>

## Network it to the runtime

The model containers publish nothing on the host — only the gateway does — so the stack coexists with others without port conflicts.

<Tabs>
<Tab title="Same host">
Put both stacks on one network, or reach the gateway over the host address:

```bash
MODEL_SERVER_URL=http://host.docker.internal:8100   # Docker Desktop
MODEL_SERVER_URL=http://172.17.0.1:8100             # Linux bridge
```
</Tab>

<Tab title="Separate hosts">
```bash
MODEL_SERVER_URL=https://models.internal.example.com
```

Keep it on a private network. The gateway has **no authentication** — anything that can reach `:8100` can use your GPUs.
</Tab>
</Tabs>

## Configure an agent

STT and TTS have first-class local providers — pick them like any other provider, no `base_url` needed:

```json
{
  "models": {
    "stt_config": { "provider": "indic_nemotron", "model": "indic-nemotron-600m", "language": "hi" },
    "tts_config": { "provider": "indic_orpheus", "model": "orpheus-indic", "voice": "Amit" }
  }
}
```

Both read the gateway address from environment variables at service-creation time, not from agent config — set `MODEL_SERVER_URL` (`indic_orpheus`, OpenAI-shaped HTTP) and `MODEL_SERVER_WS_URL` (`indic_nemotron`, raw WebSocket) on the runtime. See [Providers → The local providers](../../developer/services/providers#the-local-providers) for the field reference.

No local LLM provider exists yet, so an LLM still has to go through an OpenAI-compatible `base_url` on the `openai` provider:

```json
{
  "models": {
    "llm_config": {
      "provider": "openai",
      "model": "qwen3.5-4b",
      "base_url": "http://models.internal:8100/v1"
    }
  }
}
```

The model id must match what `GET /models` reports. Mixing is fine — a self-hosted LLM with cloud STT and TTS is a valid configuration, and so is a self-hosted `indic_orpheus`/`indic_nemotron` pair with a cloud LLM.

## Verify

Work outward, one layer at a time.

**1. The gateway answers:**

```bash
curl -s localhost:8100/v1/models
```

**2. Each modality works standalone:**

```bash
curl -s -X POST localhost:8100/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "Testing one two three", "voice": "default"}' \
  -o out.wav

curl -s -X POST localhost:8100/v1/audio/transcriptions \
  -F file=@out.wav
```

A round trip — TTS speaks a sentence and STT transcribes it back — is the check the maintainers used.

**3. Then a call.** This is the unverified step. Watch the runtime logs closely:

```bash
docker compose logs -f runtime
```

## Known gaps

| Gap | Status |
| --- | --- |
| A real call through the runtime to the gateway | **Not tested** |
| The LLM slot | **Never built or started**; its vLLM flags are unverified; no `apps/providers/local/` LLM provider exists to select it |
| `apps/providers/local/` STT/TTS | Two providers ship: `indic_nemotron` (STT), `indic_orpheus` (TTS) — see [Providers → The local providers](../../developer/services/providers#the-local-providers) |
| Model catalog sharing | `models.yaml` is the model server's own catalogue; the platform's provider catalog is separate. The two share a slot id (`GATEWAY_MODEL_ID` in each local provider's `catalog.py`), not a provider id |

The per-model pages under [Model server](../../developer/model-server/overview) state what has and has not run on hardware. Read them before choosing a model — `ready` in `models.yaml` means "the folder exists with a Dockerfile", not "tested".

## Related

* [Model server overview](../../developer/model-server/overview)
* [Gateway API](../../developer/model-server/gateway-api)
* [Running on GPUs](../../developer/model-server/gpu-operations)
* [Provider registry](../../developer/reference/provider-registry)
* [Environment variables](../../developer/reference/environment-variables)
