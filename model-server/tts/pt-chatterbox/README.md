# pt-chatterbox (model-server slot notes)

Brazilian Portuguese TTS:
[FearL0rd/Chatterbox-TTS-Portuguese](https://huggingface.co/FearL0rd/Chatterbox-TTS-Portuguese),
a fine-tune of Resemble AI's Chatterbox (MIT, not gated, ~3.2 GB). Built for
the `feat/nees-demo` POC; see `deploy/nees-demo/RUNBOOK.md`.

```bash
sh model-server/tts/pt-chatterbox/fetch.sh   # ~3.2 GB into ./checkpoints, BEFORE up
TTS_MODEL=pt-chatterbox                      # in model-server/.env
```

## Wire contract

| | |
|---|---|
| `POST /v1/audio/speech` | `{"input", "model", "voice", "response_format": "pcm"\|"wav"}` |
| response headers | `X-Audio-Format: pcm`, `X-Sample-Rate: 24000` |
| `GET /health` | 503 while loading, 200 when ready |
| `GET /demo` | type Portuguese text and hear it |

Chatterbox generates a whole utterance at once. The server splits the input
into sentences and streams each as soon as it is ready, so time to first audio
is one sentence's generation time. A client hang-up stops work between
sentences.

Voice: the checkpoint's built-in `conds.pt`. Any `voice` value is accepted.
Output carries Resemble's Perth watermark, as upstream does.

## Settings

All in `compose.extra.yml`, overridable from `model-server/.env`:
`PTC_EXAGGERATION`, `PTC_CFG_WEIGHT`, `PTC_TEMPERATURE`, `PTC_MAX_CHARS`,
`PTC_CUDA_MEM_GB`. On an MPS-shared GPU, `compose.mps.yml` caps the container
at `PTC_MPS_MEM_LIMIT` (8G) and `PTC_MPS_THREAD_PCT` (25%).
