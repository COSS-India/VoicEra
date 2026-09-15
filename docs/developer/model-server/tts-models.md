---
title: TTS models
description: Text-to-speech models, voices, and audio format negotiation.
---

Four models can fill the TTS slot. They differ in backbone, in how a voice is chosen, and — the part that matters most to a client — in what they put on the wire. This page covers all four and the format negotiation that lets one client decode any of them.

## Available models

| id | Model | Status | Sample rate | Format | Voice selection |
| --- | --- | --- | --- | --- | --- |
| `indic-parler` | AI4Bharat Indic Parler TTS | `ready` | 44100 | `pcm_f32le` | free-text description |
| `indic-mio` | SPRINGLab Indic-Mio 0.6B | `ready` | 44100 | `pcm_f32le`, also `pcm` on request | preset speaker, plus cloning |
| `orpheus` | AI4Bharat Orpheus Indic TTS | `ready` | 24000 | `pcm` | speaker name from a roster |
| `rumik-oss-1` | Rumik OSS-1 3B | `ready` | 24000 | `pcm` | any of four voices, in any language |
| `omnivoice` | k2-fsa OmniVoice 0.6B | `planned` | — | — | cloning |

Set the one you want with `TTS_MODEL` in `model-server/.env`. Statuses are from `model-server/models.yaml`.

<Note>
Only `indic-parler` has been run on VoicEra's hardware. `models.yaml` records "Not yet run on hardware" against `orpheus`, `indic-mio` and `rumik-oss-1`, and their folder READMEs repeat it: for `indic-mio`, "neither container has been built or started". `ready` means the folder exists with a Dockerfile, not that the model is verified here.
</Note>

`omnivoice` is `planned` and needs its own runtime — it is diffusion-style, so not vLLM-servable.

## indic-parler

AI4Bharat's Indic Parler TTS with a custom inference engine: paged KV cache, continuous batching, CUDA graphs, and incremental DAC decoding. Covers the same 23 Indic languages as `indic-conformer`.

The voice is chosen by a **free-text description** rather than a fixed preset list, so `voice` and `instructions` are recomposed into one prompt on the server. `tests/test_tts_request_parity.py` pins that they recompose into exactly the prompt the model used to get.

```bash
docker compose -f compose.model-server.yml --project-directory . up -d --build tts
```

`fetch.sh` in the folder downloads the checkpoints into `checkpoints/`.

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/audio/speech` | OpenAI-compatible; streams raw float32 PCM as it generates |
| `GET /health` | ready to serve |

The response carries `X-Sample-Rate` (44100) and `X-Audio-Format`. Chunked HTTP can split a 4-byte float across reads, so a client that concatenates chunks blindly gets noise — carry the remainder forward. `tests/test_pcm_chunk_boundaries.py` pins that.

It needs an NVIDIA GPU of Ada generation or newer; the engine leans on CUDA graphs and flashinfer. Warm time-to-first-audio on an H200 is around 250 ms, roughly 1.5 s cold.

The Parler checkpoint comes from Drive, but the tokenizer and T5 encoder are pulled from `ai4bharat/indic-parler-tts`, which is **gated**. See [Running on GPUs](gpu-operations) for the two ways round that.

## orpheus

A Llama-3.2-3B backbone with a SNAC codec, served by vLLM with continuous batching. 23 Indian languages on the current (v2) roster.

**The speaker name picks the language.** Every speaker in the roster belongs to exactly one language, so `voice="Amit"` is Hindi and `voice="Anitha"` is Tamil. `voice` and `language` are therefore not independent — which is different from `indic-parler`, where the voice is a free-text description and language is a separate field.

`src/orpheus_server/` is the upstream project as its authors wrote it, excluded from VoicEra's ruff config on purpose. Two changes were made, both about fitting the slot rather than changing the model:

1. **Port.** The image listened on 9000; the TTS slot is addressed as `tts:8002`. `PORT` is honoured so the folder is not welded to VoicEra's numbering.
2. **Self-description.** `POST /v1/audio/speech` now sets `X-Audio-Format`, `X-Sample-Rate` and `X-Channels`. It already sent `X-Language` and `X-Voice`.

There is no `fetch.sh` — vLLM downloads the weights from HuggingFace into the `hf_cache` volume on first start. First start therefore takes several minutes with nothing on `/health`; watch `docker compose logs -f tts` rather than assuming it has hung. `/health` returns 503 while loading and 200 once warmup and CUDA graph capture have finished, which is exactly what the gateway's probe wants.

The upstream server also exposes `/v1/tts`, `/v1/tts/stream`, a `/v1/tts/ws` WebSocket, `/v1/voices`, `/v1/styles` and `/metrics`. The gateway forwards only the OpenAI routes, so those are reachable with `docker compose exec` for debugging but are not part of the slot contract.

Worth knowing if you touch the streaming path: the authors measured which formats survive being sent in chunks, and `flac` does not — libsndfile seeks back and patches the header at close, and that patch never reaches a client whose first bytes already went out. Only `pcm` and `mp3` stream.

Roughly 7 GB for a 3B backbone in bf16 plus cache. Being vLLM-backed, it takes a memory reservation at startup the same way the LLM slot does; the KV-cache ratios are documented in `tts/orpheus/config.yaml`.

## indic-mio

A Qwen3-0.6B backbone with the MioCodec vocoder. Voice is a preset speaker embedding rather than a text description, and the embedding carries the accent, so `language` is informational here.

**Two containers, and why.** This is the first model here that is not one process. Token generation is delegated to a **vLLM sidecar** serving `SPRINGLab/Indic-Mio`; the model's own container does only the MioCodec decode and the orchestration. That is how upstream runs it, and it is not worth undoing: the model's Dockerfile pins torch 2.7.1/cu128 for Blackwell `sm_120` kernels, and vLLM's own image brings a different torch.

So the folder brings the sidecar with it, in `compose.extra.yml`. The slot contract is unchanged — one service named `tts` on 8002 answering the OpenAI route — and the sidecar is an internal service only `tts` talks to, publishing nothing on the host. `scripts/start-model-server.sh` adds the overlay automatically when this model is selected, by looking for the file rather than knowing the model.

```bash
docker compose -f compose.model-server.yml \
               -f tts/indic-mio/compose.extra.yml \
               --project-directory . up -d --build
```

<Warning>
Watch the sidecar's memory setting. Upstream uses `--gpu-memory-utilization 0.35`, which is a fraction of the card's *total* memory — on a 143 GB H200 that reserves about 50 GB, on a GPU shared with production through MPS, which does not partition memory. The overlay defaults to `0.06` (~8.6 GB) and exposes `MIO_VLLM_GPU_MEMORY_UTILIZATION` to change it. This is a **second** reservation on the same card as `VLLM_GPU_MEMORY_UTILIZATION`, not an alternative to it.
</Warning>

The upstream server spoke a WebSocket protocol — one JSON message in, float32 frames out, `{"type":"done"}` to finish. That is gone. `server.py` now serves:

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/audio/speech` | OpenAI-compatible; streams PCM as it is produced |
| `GET /health` | 503 until the codec is loaded and the engine is up |
| `GET /v1/voices` | speaker roster, read from `voices/manifest.json` |

The engine is untouched; only the transport changed, and it bought two things. **Cancellation is free** — `synthesize_stream` is an async generator, so when the caller hangs up mid-sentence Starlette closes it, `GeneratorExit` unwinds into the aiohttp response reading from vLLM, and that request is aborted. **Self-description** — responses carry `X-Audio-Format`, `X-Sample-Rate` and `X-Channels`.

`UPSTREAM-README.md` in the folder is the original documentation, kept verbatim; note that it still describes the WebSocket protocol.

No `fetch.sh`: the codec's weights come from HuggingFace on first start into the `hf_cache` volume, and the backbone comes down in the sidecar. Watch `docker compose logs -f tts vllm-mio` rather than waiting on `/health`, which stays 503 until the codec has loaded.

## rumik-oss-1

A Cohere2-style 3B backbone emitting [Mimi](https://huggingface.co/kyutai/mimi) codec tokens, eight per frame at 12.5 Hz — so eight tokens are one 80 ms frame, 1920 samples, and realtime is 100 tokens per second of speech.

<Warning>
**Licence: CC-BY-NC-4.0 with an acceptable-use addendum — research and non-commercial use only.** A commercial deployment needs separate permission from Rumik. This is the only model in `models.yaml` with that restriction, which is why the catalogue gained a `license:` field with this entry. Nothing in the stack enforces it.
</Warning>

**Any voice speaks any language.** There are four — Ira, Aisha, Siya, Zoya — and each covers all 22 languages, including code-switched text and romanized input. That is the opposite of `orpheus`, where the speaker name *is* the language selector and `voice` and `language` are not independent. Here they are independent, and the script carries the language.

Delivery is a free-text `<description="...">` prefix — emotion, accent and pace, comma-separated, as in `"happy, Hindi accent, steady pace"` — carried on OpenAI's `instructions`, the same field `indic-parler` uses. `<laugh>`, `<chuckle>` and `<sigh>` work inline in `input`.

**The folder does not run the checkpoint's own `server.py`,** which is the one real decision in it. That server exists and answers `POST /v1/audio/speech`, so the slot contract looks free — but it takes `speaker` rather than `voice`, and pydantic ignores unknown fields, so an OpenAI client asking for `voice="Zoya"` is served Ira with nothing logged; it sets no `X-Audio-Format` or `X-Sample-Rate`; it buffers the whole clip into a WAV before responding; and a client hanging up cancels nothing.

Streaming it needed a seam. `generate_audio()` is a hand-written per-token loop with no `streamer`, no callback and no `LogitsProcessor` — but it calls `self._constrained_sample(...)` once per token. The folder wraps that one call, so the upstream loop runs verbatim (sampling, the sigmoid stop head, the constrained vocabulary) and only the token stream is tapped on its way past. The same seam is the interrupt: the tap raises on its next call, unwinding the loop from the inside, which is the only way to stop a blocking generation from outside its own thread.

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/audio/speech` | OpenAI-compatible; `stream_format` `audio` or `sse` |
| `GET /health` | 503 until the checkpoint and codec are loaded |
| `GET /v1/voices` | the roster, read from the checkpoint's own `config.json` |
| `GET /demo` | a page that plays the stream as it arrives |

`fetch.sh` downloads ~7 GB into `models/` before the build. The repo is **public** — no token and no licence click-through, unlike `bodhan-ai/indic-speak` next door — so press Enter at the HuggingFace token prompt. The Mimi decoder ships inside the same repo under `codec/`, so unlike `orpheus` this folder needs no second HuggingFace repo at startup and runs airgapped once fetched; do not copy Orpheus's `HF_HUB_OFFLINE` pin onto it.

Two things are unverified and both are visible rather than hidden. The **realtime factor**: one 3B forward per token in Python, no continuous batching, no CUDA graphs, against a 100 tok/s bar — so `RUMIK_MAX_CONCURRENCY` defaults to 2 and the response carries `X-TTFA-Ms` and `X-RTF` so it is measured rather than assumed. The **streaming decode window**: Mimi in `transformers` carries no state between `decode()` calls, so each chunk is decoded with `RUMIK_DECODE_CONTEXT_FRAMES` (32) preceding frames as context and only the new samples kept. Too small does not error — it puts a seam at every chunk boundary. The folder README has the comparison to run.

## Format negotiation

The models in this slot disagree on the wire, and none of them is wrong:

| | Indic Parler | Indic-Mio | Orpheus | Rumik OSS-1 |
| --- | --- | --- | --- | --- |
| sample rate | 44,100 Hz | 44,100 Hz | 24,000 Hz | 24,000 Hz |
| sample width | float32 | float32 (16-bit on request) | signed 16-bit | signed 16-bit |
| format name | `pcm_f32le` | `pcm_f32le` | `pcm` | `pcm` |

OpenAI's `response_format` vocabulary is `mp3`, `opus`, `aac`, `flac`, `wav`, `pcm` — so Orpheus and Rumik are the compliant ones, and `pcm_f32le` is an extension Indic Parler serves because float32 is what its engine produces. Two models agreeing is not the same as the question going away: the client still decodes by what the response declares, never by which model it thinks it reached.

The client therefore cannot assume a width or a rate. It reads `X-Audio-Format` and `X-Sample-Rate` off the response and decodes accordingly, which is why the contract requires a model to declare them. Getting this wrong does not raise an error — it produces plausible bytes that sound like noise on a phone line. A format the client cannot decode produces a clear error naming it, never silence.

`tests/test_tts_format_negotiation.py` pins both the decoder table and the chunk-boundary handling, which is width-dependent: a sample split across two HTTP reads desynchronises everything after it, and a 2-byte model re-opens that bug if the width is hardcoded to 4. The test extracts the decoder from the real client source, so it fails when that drifts rather than passing against a copy. It also checks that gain never wraps.

## Barge-in and GPU release

TTS moved *off* WebSockets to plain HTTP, which gave cancellation for free. Direction of travel decides the transport: TTS is one-directional — text in, audio out — so HTTP does the same job with less machinery.

When the caller interrupts, Pipecat stops reading the response, the connection drops, and that drop travels through the gateway to the TTS server, which frees the GPU slot. For `indic-parler` the server evicts the request from the batch; for `indic-mio` the async generator's `GeneratorExit` aborts the vLLM request; for `rumik-oss-1` the same `GeneratorExit` trips a flag that the sampling tap raises on at the next token, unwinding the model's own generation loop from the inside — a blocking loop in a worker thread cannot be stopped any other way. Either way generation stops rather than finishing a sentence nobody is listening to.

That propagation is what `tests/test_gateway_streaming.py` checks: the gateway streams rather than buffers, and a client disconnect reaches the upstream. The stopping-work-on-hangup row of the [container contract](adding-a-model) exists for exactly this.

## Voices

**indic-parler** — free-text description. `models.yaml` records one preset, `Divya`, plus `free_text_description: true` and no cloning.

**orpheus** — a fixed roster, currently `tts/orpheus/voices-v2.json`: 23 languages, with 14 speaking styles (`news` is the default — `AIR style news`, `TV style news`, `educational lecture`, `single person narration audiobook`, `children's stories`, `advertisements`, `Customer Care`, and six emotion tags: happy, sad, anger, fear, surprise, disgust). Every speaker name is unique, which is what lets an OpenAI client pick a language using only the standard `voice` field. `GET /v1/voices` lists them.

<Note>
The folder also still carries the older `voices.json` (v1): 12 ALL-CAPS styles (`CONV` default, plus `WIKI`, `NEWS`, `BOOK`, ...) across the same 22 languages minus Bhili, and a completely different style vocabulary from v2 — the two rosters are not interchangeable, `model-server/tests/test_orpheus_roster.py` pins that `compose.extra.yml`'s `ORPHEUS_VOICES_FILE` matches whichever checkpoint `models.yaml` records for this slot. Which file is actually loaded is a deployment detail, not a docs one — check `ORPHEUS_VOICES_FILE` in the running `compose.extra.yml` before trusting either list. VoicEra's `indic_orpheus` provider (see [Providers → Indic Orpheus](../services/providers#indic-orpheus-tts)) is written against v2.
</Note>

**rumik-oss-1** — four: Ira (default), Aisha, Siya, Zoya, read from the checkpoint's own `config.json` rather than a roster file, and served at `GET /v1/voices`. Every one covers every language, so there is no voice-per-language table to keep in step with a checkpoint. Expressiveness lives in the free-text delivery description instead of a style roster, so there is no fixed vocabulary to get wrong — and equally nothing that rejects a typo, which is the trade.

**indic-mio** — five preset speakers built from AI4Bharat Rasa reference clips: Aditi (default), Meera, Ananya, Rahul, Arjun. It is a zero-shot voice-cloning model, so a voice is a speaker embedding derived from one reference clip. The embedding is timbre only, so one voice works across all 22 Indic languages plus English — you do not need a voice per language.

The layout is a manifest plus one clip each:

```text
voices/
  manifest.json      # {"default": <id>, "voices": [{name, gender, ref, source}, ...]}
  refs/<ref>.wav     # one clean reference clip per voice (5-15s, single speaker)
```

At startup the server derives each voice's embedding from its ref clip once and caches it under `MIO_VOICES_CACHE_DIR` (default inside the HuggingFace cache volume, so it persists). If `manifest.json` is absent or no ref clip is usable, the server falls back to a single legacy embedding rather than failing.

To add a voice, add an entry `{name, gender, ref}` to `manifest.json` and a matching mono wav in `refs/`. `name` is the voice id shown to users and stored in the agent's `tts_model.speaker`, so keep it stable once shipped. `scripts/build_voices.py` pre-bakes the embeddings so first boot is instant; `scripts/fetch_rasa_refs.py` curates new candidates from the gated `ai4bharat/Rasa` dataset (CC-BY-4.0 — see `voices/NOTICE`).

## Related

* [STT models](stt-models)
* [Adding a model](adding-a-model)
* [Gateway API](gateway-api)
* [Running on GPUs](gpu-operations)
