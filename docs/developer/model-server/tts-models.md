---
title: TTS models
description: Text-to-speech models, voices, and audio format negotiation.
---

Three models can fill the TTS slot. They differ in backbone, in how a voice is chosen, and — the part that matters most to a client — in what they put on the wire. This page covers all three and the format negotiation that lets one client decode any of them.

## Available models

| id | Model | Status | Sample rate | Format | Voice selection |
| --- | --- | --- | --- | --- | --- |
| `indic-parler` | AI4Bharat Indic Parler TTS | `ready` | 44100 | `pcm_f32le` | free-text description |
| `indic-mio` | SPRINGLab Indic-Mio 0.6B | `ready` | 44100 | `pcm_f32le`, also `pcm` on request | preset speaker, plus cloning |
| `orpheus` | AI4Bharat Orpheus Indic TTS | `ready` | 24000 | `pcm` | speaker name from a roster |
| `omnivoice` | k2-fsa OmniVoice 0.6B | `planned` | — | — | cloning |

Set the one you want with `TTS_MODEL` in `model-server/.env`. Statuses are from `model-server/models.yaml`.

<Note>
`indic-parler` and `orpheus` have run on VoicEra's hardware; `indic-mio` has not. `models.yaml` still records "Not yet run on hardware" against `indic-mio`, and its folder README repeats it: "neither container has been built or started". `ready` means the folder exists with a Dockerfile, not that the model is verified here. Orpheus has also been load-tested — see [Capacity](#capacity).
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

A Llama-3.2-3B backbone served by vLLM with continuous batching. The backbone emits SNAC codes; the slot turns them into audio with SNAC's quantizer and the checkpoint's own fine-tuned **Vocos** decoder, not SNAC's decoder. 23 Indian languages on the current (v2) roster.

**The speaker name picks the language.** Every speaker in the roster belongs to exactly one language, so `voice="Amit"` is Hindi and `voice="Anitha"` is Tamil. `voice` and `language` are therefore not independent — which is different from `indic-parler`, where the voice is a free-text description and language is a separate field.

`src/orpheus_server/` started as the upstream project as its authors wrote it, excluded from VoicEra's ruff config on purpose. It has since been changed to fit the slot and to match the released `bodhan-ai/indic-speak` checkpoint:

1. **Port.** The image listened on 9000; the TTS slot is addressed as `tts:8002`. `PORT` is honoured so the folder is not welded to VoicEra's numbering.
2. **Self-description.** `POST /v1/audio/speech` now sets `X-Audio-Format`, `X-Sample-Rate` and `X-Channels`. It already sent `X-Language` and `X-Voice`.
3. **Vocos decoder.** `codec.py` runs `quantizer.from_codes()` and then the Vocos decoder from `vocos/best.pt` beside the checkpoint — the card states "Vocos replaces SNAC's decoder entirely". There is no fallback to SNAC's decoder: a missing `vocos/best.pt` fails at startup rather than decoding with the wrong model.
4. **Sampling at the card's values.** `temperature` 0.6, `top_p` 0.9, `top_k` 50 (previously not settable at all), `repetition_penalty` 1.0 (off — on SNAC codes a penalty punishes legitimately recurring codes such as silence), and `max_tokens_default` 2520, about 30 s of audio.
5. **Ending an utterance.** A duration guard caps generation by how long the text should take to read, so a missed `<|end_of_speech|>` cannot babble on to the token limit. The backbone's text eos is treated as a soft stop, obeyed only once the audio is at least half the text's expected length — the checkpoint uses that token as padding too.
6. **Codebook bounds.** Token ids that map to a code at or above 4096 are rejected as not-audio, not passed to the decoder, where they would trigger a CUDA assert or garble the output.

`fetch.sh` downloads [`bodhan-ai/indic-speak`](https://huggingface.co/bodhan-ai/indic-speak) into `tts/orpheus/models/`, which `compose.extra.yml` bind-mounts read-only at `/models`. The repo is **gated**: accept the licence on the model page, then supply `HF_TOKEN` (or log in with `huggingface-cli login`). `fetch.sh` itself reads only `HF_TOKEN`; `scripts/start-model-server.sh` also accepts `TTS_HF_TOKEN` and passes it to `fetch.sh` as `HF_TOKEN`. Run it **before** `up -d` — Docker creates a missing bind-mount source as an empty root-owned directory, so starting first gets you a model-path error rather than a clear one. `fetch.sh` checks that `model.safetensors` and `vocos/best.pt` both arrived, because a gated repo can return everything except the weights while the CLI still exits 0.

The SNAC quantizer, `hubertsiuzdak/snac_24khz`, still downloads on first start into `hf_cache`, which is why `compose.extra.yml` pins `HF_HUB_OFFLINE=0` for this slot. First start therefore takes several minutes with nothing on `/health`; watch `docker compose logs -f tts` rather than assuming it has hung. `/health` returns 503 while loading and 200 once warmup and CUDA graph capture have finished, which is exactly what the gateway's probe wants.

The upstream server also exposes `/v1/tts`, `/v1/tts/stream`, a `/v1/tts/ws` WebSocket, `/v1/voices`, `/v1/styles` (which also returns `"none": "none"`, the no-style sentinel) and `/metrics`. The gateway forwards only the OpenAI routes, so those are reachable with `docker compose exec` for debugging but are not part of the slot contract.

Worth knowing if you touch the streaming path: the authors measured which formats survive being sent in chunks, and `flac` does not — libsndfile seeks back and patches the header at close, and that patch never reaches a client whose first bytes already went out. Only `pcm` and `mp3` stream.

Roughly 7 GB for a 3B backbone in bf16 plus cache. Being vLLM-backed, it takes a memory reservation at startup the same way the LLM slot does; the KV-cache ratios are documented in `tts/orpheus/config.yaml`.

### Tuning

Orpheus settings live in `model-server/.env`, in its Orpheus section. Compose passes them into the container through `tts/orpheus/compose.extra.yml`, where every one has a default, and they override `config.yaml`. The folder's own `tts/orpheus/.env.example` is now only a pointer — nothing reads it.

| Variable | Compose default | What it does |
| --- | --- | --- |
| `ORPHEUS_MODEL_PATH` | `/models/indic-speak` | Where `fetch.sh` puts the checkpoint. An older `.env` pinning a previous checkpoint wins over this. |
| `ORPHEUS_VOCOS_PATH` | empty | Empty means `<model>/vocos/best.pt`. Set only to point elsewhere. |
| `ORPHEUS_LEFT_CONTEXT_FRAMES` / `ORPHEUS_RIGHT_CONTEXT_FRAMES` | `4` / `4` | Vocos is non-causal, so each emitted frame is decoded with real audio either side. 4 + 4 measured 0.007% peak error against a whole-utterance decode; 3 + 3 left 3.0%. Each right-context frame adds about 30 ms before first audio. |
| `ORPHEUS_EMIT_FRAMES` | `1` | Frames emitted per decode — 85 ms chunks, the finest barge-in granularity. |
| `ORPHEUS_DURATION_GUARD`, `ORPHEUS_GUARD_CHARS_PER_SECOND`, `ORPHEUS_GUARD_HEADROOM`, `ORPHEUS_GUARD_FLOOR_TOKENS` | `true`, `8.0`, `3.0`, `512` | The runaway cap: (characters ÷ 8) seconds of expected audio × 3, never below 512 tokens. |
| `ORPHEUS_SOFT_TEXT_EOS`, `ORPHEUS_SOFT_TEXT_EOS_MIN_FRACTION` | `true`, `0.5` | Believe the backbone's text eos only after this fraction of the expected audio. `0.0` obeys it blindly. |
| `ORPHEUS_TEMPERATURE`, `ORPHEUS_TOP_P`, `ORPHEUS_TOP_K`, `ORPHEUS_REPETITION_PENALTY` | `0.6`, `0.9`, `50`, `1.0` | Sampling, at the checkpoint card's values. |
| `ORPHEUS_MAX_TOKENS_DEFAULT` | `2520` | The card's `max_new_tokens`, about 30 s. |
| `ORPHEUS_MAX_NUM_SEQS`, `ORPHEUS_DECODER_MAX_BATCH` | `32`, `32` | Admission limit and decoder batch. Keep them equal, or decoding queues behind generation. |
| `ORPHEUS_WARMUP_WIDTHS` | `1,2,4,8,16,32` | Batch widths compiled at startup; should reach `ORPHEUS_MAX_NUM_SEQS`. |
| `ORPHEUS_GPU_MEMORY_UTILIZATION` | `0.12` | Sized for a card shared with other slots. |

<Warning>
`model-server/.env.example` does not ship the compose defaults. It sets `ORPHEUS_MAX_NUM_SEQS=64`, `ORPHEUS_DECODER_MAX_BATCH=64`, `ORPHEUS_WARMUP_WIDTHS=1,2,4,8,16,32,64` — sized for Orpheus alone on a dedicated H200 — and `ORPHEUS_REPETITION_PENALTY=1.2`, where compose and `config.yaml` say `1.0`. Copy it to `.env` and those values win. Check which you meant before deploying on a shared card.
</Warning>

### Capacity

Measured with `tests/concurrency-bench/` on a dedicated H200 NVL: every stream stays real time (p95 RTF below 1) up to **64** concurrent requests; at 128 all of them fall behind (p95 RTF 1.05–1.31). The server runs at most `ORPHEUS_MAX_NUM_SEQS` at once and queues the rest, which is why `.env.example` sets 64. On other GPUs, re-measure before raising it. See [Running on GPUs](gpu-operations#checking-a-live-box).

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

## Format negotiation

Two TTS models in this slot disagree on the wire, and neither is wrong:

| | Indic Parler | Indic-Mio | Orpheus |
| --- | --- | --- | --- |
| sample rate | 44,100 Hz | 44,100 Hz | 24,000 Hz |
| sample width | float32 | float32 (16-bit on request) | signed 16-bit |
| format name | `pcm_f32le` | `pcm_f32le` | `pcm` |

OpenAI's `response_format` vocabulary is `mp3`, `opus`, `aac`, `flac`, `wav`, `pcm` — so Orpheus is the compliant one, and `pcm_f32le` is an extension Indic Parler serves because float32 is what its engine produces.

The client therefore cannot assume a width or a rate. It reads `X-Audio-Format` and `X-Sample-Rate` off the response and decodes accordingly, which is why the contract requires a model to declare them. Getting this wrong does not raise an error — it produces plausible bytes that sound like noise on a phone line. A format the client cannot decode produces a clear error naming it, never silence.

`tests/test_tts_format_negotiation.py` pins both the decoder table and the chunk-boundary handling, which is width-dependent: a sample split across two HTTP reads desynchronises everything after it, and a 2-byte model re-opens that bug if the width is hardcoded to 4. The test extracts the decoder from the real client source, so it fails when that drifts rather than passing against a copy. It also checks that gain never wraps.

## Barge-in and GPU release

TTS moved *off* WebSockets to plain HTTP, which gave cancellation for free. Direction of travel decides the transport: TTS is one-directional — text in, audio out — so HTTP does the same job with less machinery.

When the caller interrupts, Pipecat stops reading the response, the connection drops, and that drop travels through the gateway to the TTS server, which frees the GPU slot. For `indic-parler` the server evicts the request from the batch; for `indic-mio` the async generator's `GeneratorExit` aborts the vLLM request. Either way generation stops rather than finishing a sentence nobody is listening to.

That propagation is what `tests/test_gateway_streaming.py` checks: the gateway streams rather than buffers, and a client disconnect reaches the upstream. The stopping-work-on-hangup row of the [container contract](adding-a-model) exists for exactly this.

## Voices

**indic-parler** — free-text description. `models.yaml` records one preset, `Divya`, plus `free_text_description: true` and no cloning.

**orpheus** — a fixed roster, currently `tts/orpheus/voices-v2.json`: 23 languages, with 14 speaking styles (`news` is the default — `AIR style news`, `TV style news`, `educational lecture`, `single person narration audiobook`, `children's stories`, `advertisements`, `Customer Care`, and six emotion tags: happy, sad, anger, fear, surprise, disgust). Every speaker name is unique, which is what lets an OpenAI client pick a language using only the standard `voice` field. `GET /v1/voices` lists them. Pass the style `none` to send the prompt with no style block at all; omitting a style gives the roster default. `none` is reserved — a roster that defines a style by that name fails to load.

<Note>
The folder also still carries the older `voices.json` (v1): 12 ALL-CAPS styles (`CONV` default, plus `WIKI`, `NEWS`, `BOOK`, ...) across the same 22 languages minus Bhili, and a completely different style vocabulary from v2 — the two rosters are not interchangeable, `model-server/tests/test_orpheus_roster.py` pins that `compose.extra.yml`'s `ORPHEUS_VOICES_FILE` matches whichever checkpoint `models.yaml` records for this slot. Which file is actually loaded is a deployment detail, not a docs one — check `ORPHEUS_VOICES_FILE` in the running `compose.extra.yml` before trusting either list. VoicEra's `indic_orpheus` provider (see [Providers → Indic Orpheus](../services/providers#indic-orpheus-tts)) is written against v2.
</Note>

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
