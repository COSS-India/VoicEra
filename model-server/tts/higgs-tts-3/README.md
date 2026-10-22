# Higgs TTS 3 (TTS)

Boson AI's [Higgs TTS 3](https://huggingface.co/bosonai/higgs-tts-3-4b): a ~4B
autoregressive TTS. It outputs **24 kHz mono**, clones a voice zero-shot from a
reference clip, and takes inline control tags for emotion, style and prosody.
It fills the TTS slot when `model-server/.env` has `TTS_MODEL=higgs-tts-3`.

> **Licence: Boson Higgs TTS 3 Research and Non-Commercial License.** You can
> use it for research and non-commercial work. A product, a hosted API or a
> resale needs a commercial licence from Boson. VoicEra deploys it as a DPG and
> sells nothing with it, which is why it is in this catalogue. Like
> `rumik-oss-1`, its `models.yaml` entry carries `license:` so nobody misses
> this. Cloning a real person's voice without their consent is prohibited by
> the licence.

## Two containers, and why

```
caller ──► gateway :8100 ──► tts (this folder's adapter) :8002 ──► higgs-sglang :8000
                                 voices, tags, formats              SGLang-Omni + Higgs, GPU
```

Generation runs in an **SGLang-Omni sidecar** that `compose.extra.yml` brings,
as `tts/indic-mio` does with vLLM. SGLang-Omni already serves Higgs on an
OpenAI-shaped `/v1/audio/speech` and streams raw PCM. Its image (CUDA, SGLang,
UCX, flash-attn) is not something to rebuild inside a model folder. The slot's
`tts` container is a small adapter with no torch. It adds what the slot
contract needs and the sidecar doesn't provide:

| | sidecar alone | through the adapter |
|---|---|---|
| `voice` | `"default"` = a random speaker per request | a roster name → reference clip + transcript |
| `instructions` | ignored by Higgs | the fixed tag list → leading control tags; anything else is a 400 |
| `speed` | resamples (shifts pitch) | rounded to a Higgs speed tag; pitch untouched |
| headers | `X-Sample-Rate` | + `X-Audio-Format`, `X-Voice`, `X-Speed-Applied` |
| formats when streaming | pcm only | pcm, mp3, wav, flac, opus; `stream_format` audio or sse |
| errors | OpenAI envelope | OpenAI envelope, and bad requests stop before any GPU time is spent |

The sidecar is always asked for streamed PCM. So `response_format: "pcm"`
(what the voice pipeline uses) passes through byte for byte, with nothing
decoded or re-encoded on the way.

**Why the sidecar is built, not pulled.** Upstream publishes only a moving
`:dev` tag, and that image's entrypoint `git clone`s sglang-omni `main` on
every container start. `sidecar/Dockerfile` keeps the image, turns the clone
off (`SGLANG_OMNI_AUTO_CLONE=0`) and installs the released `sglang-omni==0.1.9`.
**Pin the base by digest after the first good pull**; the steps are in
`sidecar/Dockerfile`.

## The API

`POST /v1/audio/speech` uses OpenAI's request body:

```bash
curl -N http://localhost:8100/v1/audio/speech -H 'Content-Type: application/json' -d '{
  "model": "higgs-tts-3", "voice": "Meera", "response_format": "pcm",
  "input": "வணக்கம், உங்களுக்கு எப்படி உதவலாம்?",
  "instructions": "emotion:contentment"
}' -o out.pcm      # 24 kHz mono s16le
```

| field | here |
|---|---|
| `voice` | `GET /v1/voices` (Aditi, Meera, Ananya, Rahul, Arjun). A voice sets timbre and accent; the **script of `input` sets the language**. |
| `instructions` | **Fixed tags only**, comma- or space-separated. Write `emotion:elation`, `<\|emotion:elation\|>` or just `elation`. One per slot: emotion (21), style (singing, shouting, whispering), and prosody speed, pitch (`pitch_low`, `pitch_high`) and expressive (`expressive_high`, `expressive_low`). `GET /v1/voices` lists them all. |
| `speed` | 0.25–4.0, rounded to 0.65 / 0.85 / 1.0 / 1.2 / 1.4. `X-Speed-Applied` names the step used. |
| `response_format` | `pcm` (default for the pipeline), `mp3`, `wav`, `flac`, `opus`. AAC is not offered; libsndfile has no AAC encoder. |
| `stream_format` | `audio` (chunked body) or `sse` (`speech.audio.delta` / `speech.audio.done`) |
| extensions | `temperature` (0.8), `top_k` (50), `top_p` (0.8), `max_new_tokens` (1024 frames ≈ 41 s) |

**Inline tags** go into `input` where they should happen: pauses
(`<|prosody:pause|>`, `<|prosody:long_pause|>`) and sound effects, each
followed by its sound (`<|sfx:laughter|>Haha`, `<|sfx:sigh|>Uh`). A tag Higgs
doesn't know is a 400. Without that check it would be read aloud or degrade
the audio.

`GET /health` returns 503 until the sidecar is healthy **and** at least one
voice has its clip. A sidecar that is up while every voice is missing its clip
is not ready, because every request would fail.

## Voices

Higgs has no built-in speakers. A voice is a reference clip plus its
transcript, listed in `voices/manifest.json`. The clips live in `voices/refs/`
and **are not in the repo yet**. They come from the gated `ai4bharat/Rasa`
dataset (CC-BY-4.0), which needs a one-time fetch by someone whose account has
accepted Rasa's terms. See [`voices/README.md`](voices/README.md). After they
are committed, no deployment needs a token.

Until then, `HIGGS_ALLOW_ZERO_SHOT=true` lets `voice: "default"` through, and
Higgs picks its own speaker. Use it to bring the slot up and measure it. **Never
use it for calls**, because the voice changes from sentence to sentence.

## Languages

Boson's tier 1 (WER/CER under 5) covers **hi, bn, ta, te, kn, ml, mr, gu, as,
ne, ur** and English. Punjabi is tier 2 ("usable, less polished") and is
offered too. Sindhi is also tier 2 but is held back until someone has listened
to it. **Odia, Sanskrit, Bodo, Dogri, Konkani, Kashmiri, Maithili, Manipuri and
Santali are not supported.** Use orpheus, rumik-oss-1 or indic-parler for those.

## GPU memory: set this before the first start

Upstream's Higgs layout reserves **98% of the card** (encoder 0.03, engine
0.85, vocoder 0.10, each a fraction of the card's *total* memory, held whether
used or not). On ace-h200 the GPU is shared with production through MPS, which
does not partition memory. `compose.extra.yml` overrides all three:

| knob | default | on a 143 GB H200 |
|---|---|---|
| `HIGGS_ENGINE_GPU_MEMORY_FRACTION` | 0.12 | ~17 GB: ~10 GB bf16 weights + KV |
| `HIGGS_VOCODER_GPU_MEMORY_FRACTION` | 0.03 | ~4 GB, incl. its CUDA graphs |
| `HIGGS_ENCODER_GPU_MEMORY_FRACTION` | 0.02 | ~3 GB, reference encoding |

These are **H200 sizes and still unmeasured**. On an 80 GB card, use roughly
0.22 / 0.05 / 0.04. Boson's vLLM recipe measured ~60% + 25% of an 80 GB H100 at
its own defaults, which is not a lower bound.

## Running it

```bash
cd model-server
TTS_MODEL=higgs-tts-3 ../scripts/start-model-server.sh   # runs fetch.sh, adds the overlays, builds
docker compose logs -f higgs-sglang tts                  # first start: ~10 GB download + CUDA graphs
```

`fetch.sh` downloads the checkpoint into the stack's `hf_cache` volume before
the build, so a network problem shows up first and not twenty minutes in.

## Testing it on its own (ace-h200)

`compose.standalone.yml` runs the same two containers as a **separate Compose
project** (`voicera-higgs-test`), from a clone in a directory of its own.
Nothing it creates is named like anything else on the box: containers
`voicera_higgs_test_*`, images `voicera-higgs-test/*`, and its own network and
cache volume. It **publishes no host port**. It is reached through an opt-in
Cloudflare quick tunnel (a temporary `https://*.trycloudflare.com` URL with no
account) over its own Docker network. The adapter won't start without an API
key, because that URL is public.

```bash
mkdir -p ~/higgs-tts-test && cd ~/higgs-tts-test
git clone --branch feat/higgs-tts-3 --depth 1 git@github.com:COSS-India/VoicEra.git
cd VoicEra/model-server

export GPU_DEVICE_IDS=1                                    # the team's card; GPU 0 is production's
export HIGGS_HF_CACHE_VOLUME=voicera-higgs-test_hf_cache   # its own cache
export HIGGS_TEST_API_KEY=$(openssl rand -hex 24); echo "$HIGGS_TEST_API_KEY"   # keep it

sh tts/higgs-tts-3/tools/preflight.sh      # read-only: GPU room, MPS, names, disk -> GO / NO-GO
sudo -E sh tts/higgs-tts-3/fetch.sh          # ~10 GB, public repo, no token

sudo -E docker compose -p voicera-higgs-test --project-directory . \
  -f tts/higgs-tts-3/compose.standalone.yml \
  -f tts/higgs-tts-3/compose.mps.yml \
  --profile tunnel up -d --build             # leave out the mps line if preflight says so
sudo docker logs -f voicera_higgs_test_sglang                      # until it is serving
sudo docker logs voicera_higgs_test_tunnel 2>&1 | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com'
```

Then:

- **Demo page:** open `https://<name>.trycloudflare.com/demo/tts` in a browser
  and paste the key. It plays audio while it is being generated and shows
  time-to-first-audio and RTF.
- **API:** any OpenAI client with `base_url=https://<name>.trycloudflare.com/v1`
  and `api_key=$HIGGS_TEST_API_KEY`.
- **Smoke test** (on the box, so it can read nvidia-smi and the sidecar log):
  `sudo -E python3 tts/higgs-tts-3/tools/smoke_test.py --url https://<name>.trycloudflare.com --gpu 1`.
  It measures speech in six languages and at 1/4/8 concurrent streams, checks
  tags, speed, formats, SSE and refusals, hangs up mid-utterance and looks for
  the sidecar's abort, and records GPU memory. It writes `.wav` files to listen
  to and `higgs-smoke-out/report.json`.

The tunnel URL changes every time the tunnel container starts. To reach the
adapter from the box only, without the tunnel, add
`-f tts/higgs-tts-3/compose.standalone.localport.yml` (127.0.0.1:18202).

To remove everything it created:

```bash
sudo -E docker compose -p voicera-higgs-test --project-directory . \
  -f tts/higgs-tts-3/compose.standalone.yml --profile tunnel down --volumes
sudo docker image rm voicera-higgs-test/adapter:local voicera-higgs-test/sglang:0.1.9
rm -rf ~/higgs-tts-test
```

## Not yet run on hardware

Nothing here has been built or started on a GPU. The adapter is covered by
`tests/test_higgs_adapter.py` against a stub sidecar that speaks sglang-omni
0.1.9's wire format: streaming, sample alignment, tags, voices, errors, and a
hang-up closing the sidecar request. The following were read from the 0.1.9
source but not measured:

- the memory fractions above;
- time-to-first-audio and RTF on ace-h200 (Boson reports 617 ms and RTF 0.15 on
  an H100 at concurrency 1);
- that a hang-up frees the GPU end to end (sglang-omni aborts a streaming
  request on disconnect; this folder closes the connection);
- how well each voice holds up in languages other than its clip's.

Record those in `models.yaml` once measured.
