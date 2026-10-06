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
# The multilingual checkpoint is GATED. Request access on its model page first:
#   https://huggingface.co/ai4bharat/indic-asr-nemotron-600m
# Bhili comes from Google Drive (see "The Bhili checkpoint" below).
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

## The Bhili checkpoint

Bhili is served from AI4Bharat's **2026-10-05 retrain**, not the HuggingFace
release. It was shared on Google Drive alongside their inference script
(`infer_nemotron_bhb.py`), and `fetch.sh` downloads it with `gdown`.

| | path under `models/` | source |
|---|---|---|
| **current** | `bhili-asr-nemotron-600m-2026-10-05/` | Drive, file id `1ZVfylGZTlRYAX_W0WQh2Smv-sO7Clwt6` |
| previous (rollback) | `bhili-asr-nemotron-600m/` | HF `ai4bharat/bhili-asr-nemotron-600m`, `NEMOTRON_BHILI_SOURCE=hf` |

Both are `indic_nemotron_bhili_sft_lr1-averaged.nemo`, which is why the folder
carries the date: the path is the only thing that says which one is serving.
Rolling back is one line in `model-server/.env`:

```sh
NEMOTRON_BHILI_NEMO_PATH=/models/bhili-asr-nemotron-600m/indic_nemotron_bhili_sft_lr1-averaged.nemo
```

**The prompt pin.** AI4Bharat's script exists mainly to pin the language prompt
to `bhb`: NeMo's offline `transcribe` otherwise picks `auto` or `bhb` at random
per utterance. On their 4,130-utterance test set: pinned **WER 33.2**, random
50.3, `auto` 66.8. This engine never had the problem -- every stream calls
`set_prompt(model, "bhb")` -- so it needs nothing, but it is why a quick test
through NeMo's own `transcribe` can look much worse than this server.

**Both ways it can go wrong are silent**, and `/health` shows neither:

1. The path in `BHILI_NEMO_PATH` does not exist → `find_model_path` falls back
   to its built-in candidates, which is the *old* folder if it is still on disk.
   Bhili works, on the previous weights.
2. No Bhili file at all → `bhili_model` is `None` and `bhb` is served by the
   multilingual checkpoint.

`/health` says `"bhili": true` in case 1. The load line is what to check:

```sh
docker logs voicera_model_stt 2>&1 | grep 'Loading bhili'
# [Engine] Loading bhili ASR model from: /models/bhili-asr-nemotron-600m-2026-10-05/...
```

**Checksum.** AI4Bharat published none. `fetch.sh` prints the sha256 of the
first download; pin it as `BHILI_SHA256`'s default in `fetch.sh` so later
downloads are checked. Drive's failure mode is an HTML page saved under the
checkpoint's name with exit status 0, which `fetch.sh` also catches by checking
for `model_config.yaml` inside the archive.

### Testing a checkpoint without touching the live slot

`tests/bench/nemotron_standalone.sh` runs this folder as a second container on
a GPU and port you choose, with its environment taken from
`docker compose config` -- the same values the live slot gets -- and attaches to
MPS when the card has a daemon. `tests/bench/stt_ab.py` then sends the same
audio to both and reports WER/CER and every transcript that changed.

Use a separate checkout, so the branch never sits under the live stack:

```sh
git worktree add ~/voicera-bhili-test feat/nemotron-bhili-v2 && cd ~/voicera-bhili-test
LIVE=~/voicera/model-server            # wherever the live stack runs from

# 1. Weights: reuse the live multilingual download, add the new Bhili beside it.
huggingface-cli login                  # if this box is not already logged in
NEMOTRON_MODELS_DIR=$LIVE/stt/indic-nemotron/models \
  sh model-server/stt/indic-nemotron/fetch.sh     # prints the sha256 to pin

# 2. Bring up the standalone container.
GPU=1 PORT=8200 MODELS=$LIVE/stt/indic-nemotron/models ENV_FILE=$LIVE/.env \
  sh model-server/tests/bench/nemotron_standalone.sh up
sh model-server/tests/bench/nemotron_standalone.sh check    # wait for OK

# 3. Compare: live slot through the gateway vs the new container.
python3 model-server/tests/bench/stt_ab.py \
  --server old=http://127.0.0.1:8100 --server new=http://127.0.0.1:8200 \
  --language bhb --manifest bhili_test.jsonl --out ab.jsonl

# 4. Tear down.
sh model-server/tests/bench/nemotron_standalone.sh down
```

`bhili_test.jsonl` is one `{"audio_filepath": ..., "text": ...}` per line, the
format AI4Bharat's script reads; `text` is optional, and without it you get the
transcripts side by side but no WER. The WER will not match AI4Bharat's 33.2 --
theirs is offline full-utterance decoding, this is the 320 ms streaming path a
call actually uses -- so compare old against new, not against their number.

The second model costs another few GB on the card. Under MPS that memory is
shared with production, so run it outside peak hours or on a spare card.

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
