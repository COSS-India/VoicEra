# rumik-oss-1 — TTS slot

> Rumik OSS-1: 3B backbone + Mimi codec, 22 Indic languages + English, four
> voices that each cover all of them. Streams while it generates.

## Licence — read this first

**CC-BY-NC-4.0 with an acceptable-use addendum. Research and non-commercial use
only.** A commercial deployment needs separate permission from Rumik. The Mimi
codec inside `codec/` is CC-BY-4.0 and does permit commercial reuse with
attribution, but the 3B model it decodes for does not.

This is the only model in `models.yaml` carrying that restriction, which is why
the catalogue gained a `license:` field with this entry. Nothing in the stack
enforces it — it is a deployment decision, and the point of writing it here is
that nobody discovers it later.

Model card: <https://huggingface.co/rumik-ai/rumik-oss-1>

## Installing it

```bash
# from the repo root
TTS_MODEL=rumik-oss-1 ./scripts/start-model-server.sh
```

The repo is **public** — no token, no licence click-through, unlike
`bodhan-ai/indic-speak` next door. `fetch.sh` downloads ~7 GB into `models/`
before the build; the slot bind-mounts it read-only at `/models`.

Press Enter at the HuggingFace token prompt. Nothing here needs one.

Demo: <http://localhost:8100/demo/tts>

## What the container serves

| | |
|---|---|
| `POST /v1/audio/speech` | OpenAI-compatible; `stream_format` `audio` or `sse` |
| `GET /health` | 503 until the checkpoint and codec are loaded |
| `GET /v1/voices` | the roster, read from the checkpoint's own `config.json` |
| `GET /v1/models` | OpenAI-compatible single-model list |
| `GET /demo` | a page that plays the stream as it arrives |

```bash
curl -N http://localhost:8100/v1/audio/speech \
  -H 'content-type: application/json' \
  -d '{"input":"नमस्ते, आज आपका दिन कैसा रहा?",
       "voice":"Ira",
       "instructions":"happy, Hindi accent, steady pace",
       "response_format":"pcm"}' --output speech.pcm
```

`response_format` is one of `pcm` `wav` `mp3` `flac` `opus`; `pcm` and `mp3`
arrive chunked as they are produced, the other three are encoded in one pass so
their headers stay truthful. Default is `mp3`, which is OpenAI's default, but
the voice pipeline asks for `pcm`. Every response carries `X-Audio-Format` and
`X-Sample-Rate`, which is what lets one client talk to this and to Indic Parler
(44.1 kHz float32) without knowing which answered.

`voice` does **not** select the language here. That is the real difference from
`tts/orpheus`, where every speaker belongs to exactly one language and so
`voice` and `language` are not independent. All four voices cover all 22
languages, including code-switched text and romanized input.

`instructions` is the delivery description — emotion, accent, pace,
comma-separated, e.g. `"happy, Telugu accent, fast pace"`. It becomes the
model's own `<description="...">` prefix. `<laugh>`, `<chuckle>` and `<sigh>`
work inline in `input`.

`speed` is accepted and ignored: there is no rate control, and resampling would
shift pitch. Ask for pace in `instructions`. A non-default value comes back as
`X-Speed-Ignored` rather than being silently dropped.

`input` is capped at 400 characters (`RUMIK_MAX_INPUT_CHARS`), about 30 s of
speech — the model card's limit ("training utterances are limited to 30
seconds"; it advises against more than ~35 s). Generation is capped at 3072
tokens (~30.7 s), the card's stated maximum. If an utterance still reaches the
cap it is cut off, and says so: `X-Truncated: true` on a buffered response,
`"truncated": true` in the SSE `speech.audio.done` event, and a warning in the
log on every path (a chunked stream has sent its headers before it can know).

## Sampling, and where it matches the model card

| | model card / upstream | here |
|---|---|---|
| prompt | `[BOS] <text>{SPEAKER}: <description="..."> {TEXT}<audio>`, BOS added by the tokenizer | `prompt.build_prompt`; the framing ids are checked against `config.json` at startup |
| temperature / top_k / top_p | 0.8 / 30 / 1.0 | `RUMIK_TEMPERATURE` / `RUMIK_TOP_K` / vLLM's default |
| max tokens | 2048 in the example, 3072 maximum | 3072 (`RUMIK_MAX_NEW_TOKENS_*`) |
| min new tokens | 8 | `RUMIK_MIN_NEW_TOKENS`, as vLLM `min_tokens` |
| vocabulary | units + `</audio>` only | a mask in the model's `compute_logits` |
| stopping | sigmoid stop head > 0.5, or `</audio>` | the same head in `compute_logits` (`RUMIK_STOP_HEAD`), or `</audio>` |

## Why this folder does not use the checkpoint's own server.py

The repo ships a working FastAPI server that already answers
`POST /v1/audio/speech` and `GET /health`, so the slot contract looks free. It
is not, in four ways that all fail quietly:

| | shipped `server.py` | the slot |
|---|---|---|
| voice field | `speaker` — and pydantic ignores unknown fields, so `voice="Zoya"` is served as Ira with nothing logged | `voice`, OpenAI's name and the one the other TTS folders use |
| headers | `media_type="audio/wav"` and nothing else | `X-Audio-Format` + `X-Sample-Rate`; the client's decoder table knows `pcm`, `pcm_s16le`, `pcm_f32le` — **not `wav`** |
| delivery | generates every token, decodes, builds a whole WAV in a `BytesIO`, returns one `Response` | chunked while generating |
| hang-up | a blocking loop in `asyncio.to_thread`; a disconnect cancels nothing, and a global `asyncio.Lock` caps the service at one synthesis | generation stops inside the model's loop within one token |

`--port` also defaults to 7860 and ignores `PORT`, which the slot sets.

`engine.py` explains the mechanism at length. The short version: their
`generate_audio()` is a hand-written per-token loop with no `streamer`, no
callback and no `LogitsProcessor` — but it calls `self._constrained_sample(...)`
once per token, and that one call is a seam. We wrap it, so their entire loop
runs verbatim (sampling, the sigmoid stop head, the constrained vocabulary) and
we only tap the tokens on their way past. The same seam is the interrupt: the
tap raises on its next call, which unwinds their loop from the inside — which is
the only way to stop a blocking generation from outside its own thread.

## Numbers worth knowing

From `config.json`, not from a blog post:

| | |
|---|---|
| `num_quantizers` × `codebook_size` | 8 × 2048 = 16384 unit ids (`261008`–`277391`) |
| `frame_rate_hz` | 12.5 → 8 tokens = 1 frame = 80 ms = 1920 samples |
| realtime | 100 tokens per second of speech |
| `max_position_embeddings` | 8192, shared by prompt and audio — a long description shortens the utterance |
| 2048 tokens | ≈ 20.5 s of speech |
| weights | 6.76 GB in two shards, plus 385 MB of codec |

## Measured on the transformers engine: it does not reach realtime

These numbers are `RUMIK_ENGINE=transformers`, upstream's own loop. The vLLM
engine, now the default, has not been measured yet — see below.

Run on ace-h200 GPU 1 (H200 NVL 143 GB, Exclusive Process behind the shared MPS
daemon), 15 September 2026:

| | |
|---|---|
| warm throughput | **~45 tok/s** (43.1 / 48.9 / 43.3 over three runs) |
| RTF | **2.05 – 2.33** |
| time to first audio | ~370 ms |
| first generation on a cold context | 12.5 tok/s, RTF 8.0 |
| realtime needs | 100 tok/s, i.e. RTF ≤ 1.0 |

**So it is about 2.2× too slow to hold a live call.** Time-to-first-audio is
fine; what follows it is not. Generation produces 80 ms of speech roughly every
180 ms, so after the first chunk the client's buffer drains and the caller hears
gaps. That is worse than a slow start, because it sounds like a bad line.

**The cost is upstream's decode loop, not this folder.** Running
`generate_audio` directly — no server, no sampling tap, no streaming decode, no
HTTP — reproduces the same ~45 tok/s, and the served numbers match it to the
decimal (a 5.92 s utterance, 592 tokens, 13.27 s → 44.6 tok/s). The slot's layer
adds no measurable overhead. What costs is one 3B forward per token in Python,
eager, with no CUDA graphs and no continuous batching, `output_hidden_states`
materialising all 36 layers each step for the stop head, and a 277k-wide `-inf`
tensor allocated per token.

The de-interleaver is correct, which that run also settles: `DROPPED` was 1
token every time — the trailing partial frame, discarded as designed. The
round-robin resync rule never fires, so no generated audio is being thrown away.

## The vLLM engine

`RUMIK_ENGINE=vllm` (the default) serves the checkpoint through vLLM's own
Cohere2 implementation. `rumik_vllm_plugin.py` registers `RumikOSSForCausalLM`
as a subclass of it that adds exactly what upstream's class adds — the
`stop_predictor` head — plus the audio-vocabulary mask, both applied in
`compute_logits`. The plugin is an entry point because vLLM's EngineCore runs in
a spawned process; `vllm_backend.py` explains the mapping line by line.

The stop head is kept on purpose. Disabled, the model still ends on `</audio>`
by itself, but later (321–369 tokens against 273–361 with it, on the same
prompts), so dropping it is a change from the reference. `RUMIK_STOP_HEAD=false`
turns it off for comparison.

**Not yet verified on hardware.** The engine loads, captures CUDA graphs and
allocates KV cache on the H200; no utterance has been measured through it yet,
and it has not been compared against the transformers reference. Before relying
on it:

1. Synthesize the same few prompts on both engines and listen — the vLLM
   output should be indistinguishable in voice and end at the same place.
2. Record single-stream `X-RTF` and `X-Tokens-Per-Sec` here.
3. Only then raise `RUMIK_MAX_CONCURRENCY`, a step at a time, watching per-stream
   RTF stay under 1.0. It is 1 today because that was right for the
   transformers loop; under vLLM it is the only thing stopping batching —
   `RUMIK_MAX_NUM_SEQS=64` is unreachable while it is 1.

`RUMIK_GPU_MEMORY_UTILIZATION` is a fraction of the card's **total** memory and
0.12 is sized for the 143 GB H200. On a 24 GB card that is less than the
weights; use roughly (6.8 GB + ~3 GB + the KV you want) ÷ card total — ~0.45 on
24 GB, ~0.25 on 48 GB. The server refuses at startup, naming a working value,
when the fraction cannot hold the weights at all.

Until the checks above are done, treat this as **demo and evaluation grade**.

Every response carries the evidence: `X-Tokens`, `X-Tokens-Per-Sec`, `X-RTF`,
`X-TTFA-Ms`, `X-Generation-Ms` and `X-Audio-Duration-Sec` on the buffered path,
the same numbers in the SSE `speech.audio.done` event, and the demo page prints
them. Warmup logs tokens/sec at startup.

## Still unverified

**The streaming decode window.** Mimi in `transformers` carries no streaming
state between `decode()` calls, so each chunk is decoded together with
`RUMIK_DECODE_CONTEXT_FRAMES` preceding frames as context and only the new
samples are kept. 32 frames (2.56 s) is generous for a convolutional decoder
with local attention — but it is chosen, not measured. Too small does not error;
it puts a click or a seam at every chunk boundary. The check:

```python
# stream an utterance, keeping the token ids, then decode the same ids in one
# pass and compare. They should be identical to within float noise.
streamed = b"".join(chunks)                       # from POST with response_format=pcm
codes = model.audio_tokens_to_codes(token_ids)
whole = mimi.decode(codes.to(mimi.device)).audio_values[0, 0]
# max abs difference over the overlapping region should be ~1e-3 or below
```

If it is not, raise `RUMIK_DECODE_CONTEXT_FRAMES` until it is, and record the
number that worked here.

## Gotchas

- **`requirements.txt` is pinned but not yet a resolved set.** Upstream ships
  ranges (`torch>=2.4`, `transformers>=4.57,<6`); this folder pins, because two
  builds a month apart otherwise install different stacks and only one of them
  was tested. But `huggingface_hub` and `accelerate` are still ranges: no build
  has resolved them here, and an invented pin would fail the first build for a
  reason that looks like a broken Dockerfile. Freeze the whole set into a
  `constraints.txt` on the first successful build, as `tts/orpheus` did — the
  command is in `requirements.txt`.
- **`transformers` is 5.14.1, vLLM's pin, not the 4.57.6 `config.json` was
  saved with.** The vLLM path imports only `configuration_rumik_oss.py` from
  the checkpoint (it loads cleanly on 5.14.1: RoPE theta, the 36 sliding/full
  layer types and the audio ids all come through). `RUMIK_ENGINE=transformers`
  runs upstream's `modeling_rumik_oss.py`, authored against 4.57.6, and is
  best-effort on 5.x — see `requirements.txt`.
- **`trust_remote_code=True` runs code from the downloaded repo** — on the vLLM
  path only the config class, on the transformers path the modeling file too.
  Normal for a custom HF architecture, and worth knowing: the weights directory
  contains executable code, and `fetch.sh` is what put it there.
- **The tokenizer is checked at startup.** One real prompt must encode as BOS,
  the single `<text>` id, …, the single `<audio>` id, as `config.json` declares.
  A tokenizer that stopped adding BOS would otherwise degrade the voice with no
  error anywhere.
- **This folder runs airgapped; do not copy orpheus's `HF_HUB_OFFLINE` pin.**
  Orpheus pins it to `0` because its SNAC codec is a *separate* HuggingFace repo
  fetched at startup, so an `.env` carrying `HF_HUB_OFFLINE=1` for
  `stt/indic-transcribe` would hang that container in a socket read. Mimi ships
  inside this repo, in `codec/`, which `fetch.sh` has already put on local disk.
  The one case that needs the network is `RUMIK_MODEL_PATH` naming a repo id
  instead of a path.
- **Root is only for MPS hosts.** `user: "0:0"` lives in this folder's
  `compose.mps.yml`, not in `compose.extra.yml`, so it applies only when
  `compose-files.sh` detects a daemon. An MPS client must match the daemon's
  user: on a root-owned daemon a uid-1000 CUDA init does not fail, it *blocks*
  in the handshake with no log line. A Default-mode GPU keeps the unprivileged
  user. Once it has run as root, `/hf-cache` holds root-owned files, so going
  back wants a `chown 1000:1000` on that volume.
- **`audio.py` is a copy of orpheus's.** The TTS build context is
  `./tts/${TTS_MODEL}`, so a shared `tts/_common/` could only be reached by
  adding `additional_contexts` to `compose.model-server.yml` — and adding a
  model is supposed never to touch that file. Fix a bug in one and fix it in the
  other; they are the same logic over the same 24 kHz mono PCM.
- **Weights are not in the repo.** `models/` is gitignored. `fetch.sh` before
  the build, not after: Docker creates a missing bind-mount source as an empty
  root-owned directory, and the container's error is then about a model path
  rather than about the order things were done in.

## Not done here

Provider registration. A model can be catalogued, built, healthy and listed at
`/models` while no agent can name it — the failure with no symptom until a call
drops. That needs `apps/providers/local/<name>/` with a
`register_local(provider_id, gateway_model_id)` call, as `indic_orpheus` has.
See [Local providers](../../../docs/developer/guides/adding-a-provider.md).
