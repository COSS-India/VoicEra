# indic-nemotron (model-server slot notes)

AI4Bharat Nemotron Streaming ASR 600M in the STT slot.

```
STT_MODEL=indic-nemotron
```

**This folder is a copy, not a fork.** Every file except `compose.extra.yml`,
`fetch.sh`, `.env.example` and these notes is upstream's, byte for byte, and
`tests/test_nemotron_slot.py` fails if that stops being true. Two things about
it do not match the slot convention, and both are handled from outside rather
than by editing it:

| | upstream | how the slot handles it |
|---|---|---|
| port | binds 8000, hardcoded at `server.py:341` | `STT_UPSTREAM=http://stt:8000` |
| demo page | served at `/`, not `/demo` | `STT_DEMO_PATH=/` |

Its own `docker-compose.yml` stays in the folder, unused — `compose-files.sh`
only ever picks up `compose.extra.yml`. Two things in it would be wrong here: it
reserves `count: all`, taking every GPU on a box where only GPU 1 is ours, and
it publishes 8000 on the host, where this stack publishes exactly one port.

## Why it is worth having

| | how a partial transcript costs | latency |
|---|---|---|
| indic-conformer | re-transcribes the segment every 600 ms | grows with utterance length |
| indic-transcribe | AlignAtt incremental decode | 400 ms floor |
| **indic-nemotron** | cache-aware, fixed chunk | **320 ms** (selectable 160/320/640) |

27 languages from one multisoftmax checkpoint — 27 × 256 tokens = 6912 classes,
the prompt selecting which slice the decoder may draw from — plus Bhili on a
second checkpoint, with no separate enable flag. That is a superset of both
other STT models, so switching to it cannot lose a language a caller can ask
for; a test pins that.

## Setup

```sh
# Both checkpoints are GATED. Request access on both model pages first:
#   https://huggingface.co/ai4bharat/indic-asr-nemotron-600m
#   https://huggingface.co/ai4bharat/bhili-asr-nemotron-600m
huggingface-cli login
sh model-server/stt/indic-nemotron/fetch.sh      # ~4.8 GB, weights BEFORE up

echo 'STT_MODEL=indic-nemotron' >> model-server/.env
docker compose $(sh model-server/compose-files.sh) \
  --project-directory model-server up -d --build
```

**`up -d --build`, with no service name.** This model's overlay is the only one
that sets environment on the *gateway* service — `STT_UPSTREAM` and
`STT_DEMO_PATH`, because upstream binds 8000 and serves its demo at `/`.
Bringing up only `stt` replaces the model container and leaves the gateway
holding whatever it was last given, so switching between this model and another
points the gateway at the wrong port and the wrong demo path, and every request
502s. `up -d` recreates whatever's resolved config changed, which is both of
them. `setup.sh` already does it this way.

Weights first, not second: Docker creates a missing bind-mount source as an
empty root-owned directory, so starting first makes the container complain about
a model path instead of a missing download.

## Three things the deployment must declare

Read `compose.extra.yml` for the full list. These are the ones that bite:

**`ASR_ATT_CONTEXT`** — `asr_engine.py:82` defaults it to `96,7`, which is
640 ms. Upstream's own compose overrides it to `96,3` (320 ms), and we don't use
their compose. Leaving it unset would silently double the latency and look like
a slow model rather than a missing line. This is the sixth time this repo has
met that shape of bug.

**`ASR_VAD_MARGIN_DB`** — read at `session.py:57`, declared nowhere upstream:
not in their compose, not in their README.

**`ASR_DEFAULT_LANG`** — deliberately *not* declared. Their compose sets it and
their module docstring says an unnamed language falls back to it, but
`openai_api.py:40` hardcodes `DEFAULT_LANGUAGE = "hi"` and nothing reads the
variable. It does nothing, and a knob that does nothing is worse than an absent
one — it is the first thing someone reaches for when transcripts come back in
the wrong language.

## Two things to know before deploying

**There is no `auto` language, by design.** The vocabulary is sliced per
language; an unsliced decode draws from all 27 and emits cross-script nonsense.
Upstream measured two language-ID schemes and neither discriminated — slice
probability mass landed at chance, and prompt scoring picked Urdu for Hindi.
Callers must name a language, and an unknown code raises rather than defaulting
to Hindi.

**Transcripts can differ under load.** Batched GPU kernels are not batch-size
invariant, and greedy RNNT amplifies ~1e-3 encoder differences into visible
changes. Upstream documents this. It is not a bug and it is not ours, but it
will look like one the first time a load test disagrees with a manual check.

## Running on hardware

Deployed on ace-h200, GPU 1, since 2 September 2026. What `/health` reported on
first start:

```
"models_loaded": {"multilingual": true, "bhili": true}
"streaming": {"att_context_size": [96, 3], "chunk_ms": 320, "decoder": "rnnt"}
"vocab_slicing": {"num_langs": 27, "vocab_per_lang": 256}
```

The `[96, 3]` is the line worth reading. Undeclared it would have been `[96, 7]`
— 640 ms — and nothing would have looked wrong.

The two risks flagged before the first deploy both cleared: the box runs driver
610.57.04 / CUDA 13.3, comfortably above what the cu130 torch needs, and the
build never touched the `nemo` context because this Dockerfile does not
reference it.

### What the first deploy caught that the tests did not

Two gateway gaps, both invisible to a test suite that reads source rather than
what is deployed:

1. `/demo/stt` returned 404 with the gateway env set correctly — because only
   the `stt` image had been rebuilt, and the gateway's code is baked into its
   own image rather than bind-mounted. Rebuild `gateway` too when its source
   changes.
2. The page then loaded, but the microphone would not start: it fetches its
   AudioWorklet from the absolute path `/static/audio-processor.js`, which
   behind the gateway lands at the gateway root. A missing worklet surfaces in
   the browser as a microphone permissions error, which points you nowhere
   near the cause. Fixed by `STT_DEMO_ASSETS`, tested against a stub shaped
   like this server.

Both now have tests that fail without the fix.

---

Upstream's own README is kept verbatim in `UPSTREAM-README.md`, following the same convention as indic-transcribe and
orpheus: their text stays unedited so a re-push from upstream is a clean
replace, and ours lives here.
