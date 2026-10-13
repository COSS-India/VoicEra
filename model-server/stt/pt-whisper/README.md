# pt-whisper (model-server slot notes)

Brazilian Portuguese STT: [BuzzASR/portuguese](https://huggingface.co/BuzzASR/portuguese),
a Whisper-large-v3 fine-tune (1.54B, fp16, MIT, not gated). Built for the
`feat/nees-demo` POC; see `deploy/nees-demo/RUNBOOK.md`.

```bash
sh model-server/stt/pt-whisper/fetch.sh     # ~3.1 GB into ./models, BEFORE up
STT_MODEL=pt-whisper                         # in model-server/.env
```

## Wire contract

Same as `indic-nemotron`, so `apps/providers/local/pt_whisper` reuses the
Nemotron client:

| | |
|---|---|
| `WS /v1/asr/ws?language=pt` | binary PCM16 mono 16 kHz in; `{"status":"ready"}` on connect; `{"text","is_final":false}` partials; `{"action":"flush_eos"}` → one `{"text","is_final":true}` |
| `POST /v1/audio/transcriptions` | OpenAI-shaped, WAV upload |
| `GET /health` | 503 while loading, 200 when ready |
| `GET /demo` | upload a WAV and see the transcript |

Whisper has no incremental decode. Partials are produced here: every
`PTW_INTERIM_MS` (600 ms) the open segment is re-transcribed, behind Silero VAD
so silence never reaches the decoder. Turn ends are the caller's — the Pipecat
pipeline sends `flush_eos` on its own VAD stop.

## Settings

All in `compose.extra.yml`, overridable from `model-server/.env`:
`PTW_INTERIM_MS`, `PTW_MAX_BUFFER_S`, `PTW_VAD_THRESHOLD`, `PTW_NUM_BEAMS`,
`PTW_CUDA_MEM_GB`. On an MPS-shared GPU, `compose.mps.yml` caps the container
at `PTW_MPS_MEM_LIMIT` (6G) and `PTW_MPS_THREAD_PCT` (25%).
