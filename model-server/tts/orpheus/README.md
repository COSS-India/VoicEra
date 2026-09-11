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

### The decoder is not yet the one this checkpoint wants

`indic-speak` uses SNAC only as a **quantizer** — its card gives the pipeline as
`LM -> SNAC codes -> quantizer.from_codes -> z_q [B,768,L] -> Vocos -> 24 kHz`,
with a fine-tuned Vocos decoder (`vocos/best.pt`) replacing SNAC's decoder
entirely. `codec.py` here calls `SNAC.decode`, which runs quantizer *and* SNAC
decoder.

The token contract is unchanged, so this works: same codebook, same code space,
intelligible speech out. It is simply not the decoder the checkpoint was tuned
for, so fidelity is the open question — compare against the previous checkpoint
by ear before assuming the swap is neutral. `fetch.sh` pulls `vocos/` down with
everything else so wiring it up needs no second download.

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
