# Orpheus Indic TTS

AI4Bharat's Orpheus — a Llama-3.2-3B backbone with a SNAC codec, served by vLLM
with continuous batching. Fills the TTS slot; set `TTS_MODEL=orpheus` in
`model-server/.env`.

22 Indian languages. **The speaker name picks the language** — every speaker in
the roster belongs to exactly one, so `voice="Amit"` is Hindi and
`voice="Anitha"` is Tamil. `GET /v1/voices` lists them. That is different from
Indic Parler, where the voice is a free-text description and language is a
separate field.

## Vendored, not written here

The upstream project's own documentation is preserved here as
[UPSTREAM-README.md](UPSTREAM-README.md) — 522 lines covering the full API,
the speaker roster, styles and tuning. It was called `Readme.md`, which a
Windows checkout treats as the same file as `README.md`; renaming it is what
stops the two clobbering each other.


`src/orpheus_server/` is the upstream project as its authors wrote it, lifted
from the `dev-Orpheustts` branch. It is excluded from our ruff config on
purpose: restyling it would turn every future sync from upstream into a merge
conflict for no behavioural gain.

Two changes were made, both small and both about fitting the slot rather than
changing the model:

1. **Port.** The image listened on 9000; the TTS slot is addressed as `tts:8002`.
   `PORT` is honoured so the folder is not welded to our numbering.
2. **Self-description.** `POST /v1/audio/speech` now sets `X-Audio-Format`,
   `X-Sample-Rate` and `X-Channels`. It already sent `X-Language` and `X-Voice`.
   See below for why this matters.

## Audio format — the reason the headers were added

Two TTS models in this slot disagree on the wire:

| | Indic Parler | Orpheus |
|---|---|---|
| sample rate | 44,100 Hz | 24,000 Hz |
| sample width | float32 | signed 16-bit |
| format name | `pcm_f32le` (an extension) | `pcm` (OpenAI's own name) |

Neither is wrong. OpenAI's `response_format` vocabulary is `mp3`, `opus`, `aac`,
`flac`, `wav`, `pcm` — so Orpheus is the compliant one, and `pcm_f32le` is
something Indic Parler serves because float32 is what its engine produces.

The client therefore cannot assume a width or a rate. It reads `X-Audio-Format`
and `X-Sample-Rate` off the response and decodes accordingly, which is why a
model must declare them. Getting this wrong does not raise an error — it
produces plausible bytes that sound like noise on a phone line.

`tests/test_tts_format_negotiation.py` pins both the decoder table and the
chunk-boundary handling, which is width-dependent: a sample split across two
HTTP reads desynchronises everything after it, and a 2-byte model re-opens that
bug if the width is hardcoded to 4.

## Weights

`./fetch.sh` downloads [bodhan-ai/indic-speak](https://huggingface.co/bodhan-ai/indic-speak)
into `models/`, which `compose.extra.yml` bind-mounts read-only at `/models`.
The repo is **gated** — accept the licence on the model page, then supply
`HF_TOKEN`, or `TTS_HF_TOKEN` if this slot has a token of its own. Run it before
`up -d`: Docker creates a missing bind-mount source as an empty root-owned
directory, so starting first gets you a model-path error rather than a clear one.

This section previously said there was no fetcher because *"vLLM downloads the
weights from HuggingFace into the `hf_cache` volume on first start"*. That was
not true of the shipped config. `ORPHEUS_MODEL_PATH` defaults to a directory
inside a read-only bind mount, and vLLM only auto-downloads when given a repo
id — so nothing was ever fetched. The weights came from a Google Drive folder of
raw training output, assembled by hand; `UPSTREAM-README.md` still documents
that, with the folder URL left as a placeholder. What *does* download on its own
is the SNAC codec, `hubertsiuzdak/snac_24khz`, which is a repo id — probably why
the claim went unchallenged.

First start still takes several minutes with nothing on `/health` — watch
`docker compose logs -f tts` rather than assuming it has hung. `/health` returns
**503 while loading** and 200 once warmup and CUDA graph capture have finished,
which is exactly what the gateway's probe wants.

### The decoder is the checkpoint's own Vocos

`indic-speak` uses SNAC only as a **quantizer**. Its card gives the pipeline as
`LM -> SNAC codes -> quantizer.from_codes -> z_q [B,768,L] -> Vocos -> 24 kHz`
and states that "Vocos replaces SNAC's decoder entirely" — 0.56 MB of SNAC's
79 MB is used. `codec.py` does exactly that: `quantizer.from_codes()`, then the
fine-tuned Vocos decoder from `vocos/best.pt`.

SNAC's own decoder is never called, and there is no fallback to it. A missing
`vocos/best.pt` raises at startup rather than quietly decoding with the wrong
model, which is the failure this arrangement is most likely to hit — the
checkpoint's `inference.py` offers SNAC's decoder only as `stock=True`, "for
A/B", and this server ran that A/B path as its only path until the port.

**Streaming a non-causal decoder.** Vocos needs real audio either side of the
frames it emits, so `StreamingAudioBuffer` decodes a wide window and emits a
narrow one: `left_context_frames` + `emit_frames` + `right_context_frames`.
The defaults are measured, not derived — one frame decoded with N frames of
context each side, compared against a whole-utterance decode of the same codes:

| context | peak error vs whole-utterance decode |
|---|---|
| 3 + 3 | 3.024% — audible |
| **4 + 4** | **0.007% — inaudible** |
| 6 + 6 | 0.001% — no further gain |

So 4 is the knee. End to end, streaming output matches a one-shot decode to
within 9/32767 (−71 dB) on utterances up to 40 frames, and matches exactly at
4 frames and under.

`right_context_frames` is the latency knob: each frame is one more frame of
generation to wait for before the first audio goes out, about 30 ms at the
measured RTF of 0.35. `emit_frames: 1` keeps 85 ms chunks, the finest barge-in
granularity; decode costs roughly 0.4% of real time at 32 concurrent streams,
so there is nothing to buy by raising it.

## Beyond the OpenAI endpoint

The upstream server also exposes `/v1/tts` (one complete WAV),
`/v1/tts/stream` (a playable URL), a `/v1/tts/ws` WebSocket, `/v1/voices`,
`/v1/styles` and `/metrics`. The gateway forwards only the OpenAI routes, so
those are reachable with `docker compose exec` for debugging but are not part of
the slot contract.

Worth knowing if you touch the streaming path: the authors measured which
formats survive being sent in chunks, and `flac` does not — libsndfile seeks back
and patches the header at close, and that patch never reaches a client whose
first bytes already went out. Only `pcm` and `mp3` stream.

## GPU

vLLM-backed, so it takes a memory reservation at startup the same way the LLM
slot does — see `config.yaml`, where the KV-cache ratios are documented. Roughly
7 GB for a 3B backbone in bf16 plus cache. Not yet run on hardware.
