# maya2-native

Maya Research's [Maya 2 Native](https://huggingface.co/maya-research/maya2-native)
in the TTS slot: streaming text-to-speech for **11 Indic languages and English**
with **20 named voices**, served on OpenAI's `POST /v1/audio/speech`.

| | |
|---|---|
| Model | ~2.5 B parameters: Qwen3-1.7B-Base backbone (codebook 0) + 555 M depth decoder (codebooks 1–31) |
| Codec | Kyutai Mimi, 32 codebooks at 12.5 Hz — one 80 ms frame per step |
| Audio | 24 kHz mono, served as `pcm` (16-bit LE) by default; also `wav`, `mp3`, `opus`, `flac` |
| Languages | `as bn en gu hi kn ml mr or pa ta te` (`od` accepted for Odia) |
| Voices | 20 named voices, no reference audio; see the table below |
| Engine | upstream's own: continuous batching over seats, CUDA graphs, Triton kernels |
| Licence | Apache-2.0 (weights and code); Mimi CC-BY-4.0; ECAPA Apache-2.0 |

```bash
cd model-server
tts/maya2-native/fetch.sh                      # ~5.5 GB into tts/maya2-native/models/
sed -i 's/^TTS_MODEL=.*/TTS_MODEL=maya2-native/' .env
docker compose $(sh compose-files.sh) --project-directory . up -d --build tts
curl -sN localhost:8100/v1/audio/speech -H 'content-type: application/json' \
  -d '{"model":"maya2-native","input":"नमस्ते, आपका ऑर्डर कल पहुँच जाएगा।","voice":"Ahana","language":"hi"}' \
  | ffplay -f s16le -ar 24000 -ch_layout mono -
```

Demo page: `http://localhost:8100/demo/tts`.

## Why this folder is small

Upstream ships an OpenAI-compatible server (`maya3.server`) over a
continuous-batching engine: admission control with a queue deadline, cancellation
when the client disconnects, OpenAI-shaped errors, and a failure after audio has
started aborting the connection rather than ending it cleanly. That is
everything tts/rumik-oss-1 had to build for itself, so this folder **wraps**
upstream's server instead of replacing it, and adds only the slot contract:

| | upstream alone | this slot |
|---|---|---|
| `X-Audio-Format` | absent (`X-Encoding: pcm_s16le`) | on every speech response |
| default `response_format` | `wav` | `pcm` (`MAYA_DEFAULT_FORMAT`) |
| `language: "od"` | 400 | Odia (`or`) |
| `voice: "alloy"` / none | `plain`, a random speaker per request | `MAYA_DEFAULT_VOICE` |
| `instructions`, `speed != 1` | ignored / 400 | ignored, reported in `X-Instructions-Ignored` / `X-Speed-Ignored` |
| `GET /v1/voices` | upstream's shape, includes `plain` | `{"object":"list","data":[{id, languages, gender, age, description}], "default"}` |
| `POST/DELETE /v1/voices` | open to anyone | 403 unless `MAYA_VOICE_CLONING=true` |
| `GET /demo` | — | a page that plays the stream as it arrives |
| port | 8080 | `PORT` (8002) |

`contract.py` holds every one of those decisions as plain functions, and
`tests/test_maya2_native.py` tests them without a GPU. `server.py` subclasses
upstream's `Maya3Server` and overrides five methods by name (listed in its
docstring), which is why requirements.txt pins upstream to a commit.

Upstream's WebSocket (`WS /v1/tts/stream`) is still served, unchanged; the
voice pipeline does not use it.

## Language, and why the client sends it

The server can guess the language from the script, but the script does not
decide it: Marathi is written in Devanagari like Hindi, and Assamese in the
Bengali script. A guess would read every Marathi sentence as Hindi. So the
`maya2_native` provider sends the agent's language on every request, as an
OpenAI `extra_body` field, and the server maps VoicEra's canonical ids (`od`) to
the model's (`or`). A request without `language` still works — upstream detects
it from the script — which is what an off-the-shelf OpenAI client gets.

## Voices

Each voice is listed with the languages it had at least an hour of training
data in. Any voice can speak any of the twelve — the language tag drives the
text, the name drives the timbre — but outside its list it is cross-lingual,
and the response says so in `X-Voice-Untrained-Language`.

| Voice | | Trained languages |
|---|---|---|
| Ahana, Vaidehi, Malini, Charvi | female | bn en gu hi kn ml mr or pa ta te |
| Anirban, Nakul, Siddhant, Satvik | male | bn en gu hi kn ml mr or pa ta te |
| Jahnavi | female | bn en gu hi kn ml mr or ta te |
| Vasant | male | bn en gu hi kn ml mr or ta te |
| Nivedita, Tanushree | female | en hi |
| Abhay, Shaunak, Akshat | male | en hi |
| Ishwari, Vrinda | female | hi |
| Ritvik | male | hi |
| Sreekar | male | en hi te |
| Kayal | female | en ta |

**No voice lists Assamese.** The model supports it (CER 5.4 % in upstream's
evaluation), but every Assamese utterance is cross-lingual. The provider offers
the eight all-language voices for it.

The roster is read from the release's `voices/voices.json` at startup and served
at `GET /v1/voices`; the table above is for reading, not a source of truth.

## Capacity and memory

`MAYA_MAX_SEATS` streams are batched on one 80 ms tick, and memory for every seat
is allocated at startup whether it is used or not (model card, BF16 backbone,
FP16 depth decoder, 2048 KV tokens per seat):

| seats | 1 | 8 | 16 | 32 |
|---|---|---|---|---|
| steady GPU memory | 7.7 GB | 9.7 GB | 11.7 GB | 15.8 GB |

Add ~0.5 GB of CUDA context; loading peaks ~1.5 GB above steady. MPS does not
partition memory, so on ace-h200's shared GPU this number is what production is
left with. 16 is the default.

Upstream reports, on one H100 NVL with 224 concurrent WebSocket streams, 323 s of
audio per second, steady-state time-to-first-audio p50/p99 of 111/242 ms and a
per-stream RTF of 0.68; a single stream reaches first audio in ~14 ms at RTF
0.13. **Not yet measured on VoicEra's hardware.** Record the first numbers in
models.yaml when it has been.

A request that would make more than `MAYA_MAX_PENDING` requests wait for first
audio, or that waits longer than `MAYA_QUEUE_DEADLINE_MS`, is refused with 503 and
`Retry-After` — before any audio, so the caller can fall back rather than hear a
late start.

## Text normalisation

On by default (`MAYA_NORMALISE`): numbers, currency, dates, times, OTPs, phone
numbers and URLs become words in the request's language. A request can opt out
with `"normalize": false`. Upstream has two opt-in normaliser modes keyed on
`FR3_TN_URL_SPELL` / `FR3_TN_LONG_DIGITS`; leave them unset — at the pinned commit
they read a data file (`identifier_words.json`) the repository does not ship.

## Files

| | |
|---|---|
| `server.py` | upstream's server plus the slot contract; loads the model |
| `contract.py` | the request/response rules, pure functions |
| `config.py` | `MAYA_*` settings, each declared in `compose.extra.yml` |
| `fetch.sh` | release + Mimi + ECAPA into `models/`, run before the build |
| `compose.extra.yml` | the slot's environment and the read-only `/models` mount |
| `compose.mps.yml` | root user, only on a host with an MPS daemon |
| `static/demo.html` | the demo page |

## Not done yet

* **Voice cloning.** Upstream supports zero-shot cloning from 3–10 s of audio
  (`POST /v1/voices`). It is disabled: registered voices would live in one
  container's memory and vanish on restart, and nothing in VoicEra stores them.
* **A frozen `constraints.txt`** — write it from the first build that works.
* **A pinned weights revision** — set `MAYA_REVISION` to the commit verified on
  hardware.
* **Measurements on ace-h200.**
