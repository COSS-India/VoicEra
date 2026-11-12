# hima-asr

[Hima-ASR](https://huggingface.co/Prahaladha/hima-asr) in the STT slot: a 0.46B
encoder-decoder for 11 Indian languages plus English, built for code-switched
speech.

```bash
STT_MODEL=hima-asr ./scripts/start-model-server.sh
# Demo: http://localhost:8100/demo/stt
```

## What the model is

| | |
| --- | --- |
| Architecture | Qwen3-ASR-1.7B audio encoder (12.5 frames/s) → projector → Gemma-3-270M decoder, trimmed to 63,335 pieces |
| Size | 0.46B, ~0.9 GB in bf16 — the smallest model in this slot by a wide margin |
| Runtime | HuggingFace Transformers ≥ 5.13, `trust_remote_code` |
| Input | 16 kHz mono clips of 1–30 s. It transcribes whole clips; it does not stream |
| Languages | `as bn en gu hi kn ml mr or pa ta te`, plus auto-detect |
| Style | `native` (each word in its language's script) or `mixed` (English words stay Latin) |
| Licence | Apache-2.0, **except the decoder: Gemma Terms of Use** (see below) |
| Access | Public, not gated |

## How it fits the slot

Because the model only takes whole clips, this folder takes
indic-conformer's shape, not indic-nemotron's:

| Route | |
| --- | --- |
| `POST /v1/audio/transcriptions` | multipart `file` (WAV at any rate, or headerless 16 kHz int16) and `language` |
| `WS /v1/realtime?intent=transcription` | OpenAI Realtime transcription. Partials come from re-transcribing the open segment every `REALTIME_INTERIM_MS` |
| `GET /health` | 503 until the model is loaded **and warmed** |
| `GET /v1/languages` | the twelve codes, for the demo page |
| `GET /demo` | the same live demo page as indic-conformer |

`realtime_ws.py` and `realtime_protocol.py` are copies of indic-conformer's.
`tests/test_hima_asr.py` pins them, so the two models cannot drift into speaking
different protocols to the same client. The first file differs only in the
model name; the second is byte-identical.

Every request goes through one batch worker: POSTs and realtime interims share
forward passes, with one model call per language in the batch window. A
failure is confined to its language group, so one bad session cannot fail
everyone else who shared its window.

**Audio over 30 s** is split at the quietest 20 ms frame within 3 s before
each 30 s mark, and the pieces are transcribed in the same call and rejoined.
A phone turn almost never gets that long, because Silero ends it first, but a
POST upload can.

**Language.** The provider always names a language, as every STT provider here
does. `auto` (or no language) on the raw API asks the model to detect it.
`od` is accepted as an alias for `or`. Anything else gets a 400, or an
`error` event that also ends the turn on the WebSocket.

**Not served:** the model card's decision head (tone, intent, urgency yes/no
and scale questions). It is a separate 17.5M model with its own API, and this
slot's contract is audio in, text out. `fetch.sh` skips `decide/`.

## Files

| | |
| --- | --- |
| `fetch.sh` | downloads the repo **at a pinned commit** into `models/hima-asr/` |
| `Dockerfile` | CUDA 13 runtime + torch cu130 (same base as indic-conformer), Transformers, offline |
| `compose.extra.yml` | declares every `HIMA_*` / `REALTIME_*` variable; no sidecar, no extra mount |
| `server.py` | ours |
| `realtime_ws.py`, `realtime_protocol.py` | indic-conformer's, see above |
| `static/realtime.html` | indic-conformer's demo page, unchanged |

## Why the commit is pinned

`trust_remote_code` means `modeling_hima_asr.py` from the HF repo runs inside
our container. `fetch.sh` pins `HIMA_REVISION`, and the image sets
`HF_HUB_OFFLINE=1`, so the code that runs is the code someone reviewed, never
whatever the repo holds today. Moving `HIMA_REVISION` forward means reviewing
the new code, not just refreshing the download.

The slot bind-mounts this folder at `/app`, so the weights at
`models/hima-asr/` reach the container without a separate volume. If they are
missing, the server refuses to start and names `fetch.sh`.

## Configuration

Everything has a default in `compose.extra.yml`. The settings most likely to
need changing:

| Variable | Default | |
| --- | --- | --- |
| `HIMA_DTYPE` | `float32` | what the model card loads. `bfloat16` halves memory but has not been compared |
| `HIMA_STYLE` | `native` | `mixed` for code-switched English in Latin script; server-wide |
| `HIMA_REALTIME_INTERIM_MS` | `600` | partial cadence, as on indic-conformer |
| `HIMA_MAX_BATCH` | `16` | |
| `HIMA_MAX_SECONDS` | `30` | the model card's clip limit |

## Licence

Hima's own parts (the projector, its training changes and its inference code)
and the Qwen3-ASR encoder are Apache-2.0. The decoder is derived from Gemma 3,
so it is covered by the **Gemma Terms of Use**, including the prohibited-use
policy. Redistribution has to pass those terms on; see `NOTICE` in the HF repo.

## Status

**Not yet run on hardware.** These are still to be measured on ace-h200:

- VRAM at float32 and bf16
- realtime factor
- time to first partial
- how many sessions it holds
- transcript quality against indic-conformer and indic-nemotron on our own call
  audio, especially te/ta/kn/ml, where the model card claims its biggest lead

The model card's own numbers are self-reported: 12.95 average WER over its test
sets, against 12.84 for Indic-Transcribe-Core and 12.79 for Sarvam Saaras v3.
