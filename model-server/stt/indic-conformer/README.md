# Indic Conformer (STT)

AI4Bharat's 600M hybrid RNNT/CTC Conformer, served through NeMo. Fills the STT
slot; set `STT_MODEL=indic-conformer` in `model-server/.env`.

Covers 23 Indic languages. Bhili (`bhb`) uses a separate checkpoint — enable it
with `BHILI_ENABLE=yes` and point `BHILI_NEMO_PATH` at the file. The server
routes on the request's `language` field, so callers use the same endpoint
either way.

## Run

```bash
cd model-server
STT_MODEL=indic-conformer ./setup.sh
# open http://localhost:8100/demo for the live demo
./stop.sh   # when done
```

`fetch.sh` in this folder downloads the checkpoint (~2.4 GB) into `models/`.

## Live demo (browser)

With the stack running and `STT_MODEL=indic-conformer`:

1. Open **http://localhost:8100/demo** in Chrome or Firefox.
2. Pick a language, click **Start**, allow the microphone, and speak.
3. Words stream in as the server emits OpenAI Realtime `delta` events (~600 ms
   between interim passes). Click **Stop** to commit the segment.

The mic works on `localhost` over HTTP. On a remote machine you need HTTPS (or a
tunnel) — browsers block `getUserMedia` on plain HTTP except for localhost.

## API

Reached through the gateway on `:8100`, never directly — the container binds
nothing on the host.

| Endpoint | Purpose |
|----------|---------|
| `POST /v1/audio/transcriptions` | OpenAI-compatible; multipart `file` plus a `language` field |
| `WS /v1/realtime?intent=transcription` | OpenAI Realtime transcription (Pipecat `OpenAIRealtimeSTTService`); word-by-word deltas |
| `GET /health` | ready to serve |

## Pipecat (OpenAI Realtime STT)

Point Pipecat's `OpenAIRealtimeSTTService` at the gateway (or this server directly):

```python
stt = OpenAIRealtimeSTTService(
    api_key="local",
    base_url="ws://localhost:8100/v1/realtime",
    turn_detection=False,
    settings=OpenAIRealtimeSTTService.Settings(
        model="indic-conformer",
        language=Language.HI,
    ),
)
```

Audio is sent as 24 kHz PCM; the server resamples to 16 kHz for NeMo. Partials are
produced by re-transcribing the growing buffer every `REALTIME_INTERIM_MS` (default
600 ms). Multiple concurrent WebSocket sessions share the same GPU batch worker.

## Build context

The image installs the AI4Bharat NeMo fork from a local checkout rather than
cloning during the build, matching production. Compose passes it in as a named
build context; `NEMO_CONTEXT_PATH` in `.env` says where it lives, defaulting to
`~/ai4bharat_nemo`.

```bash
git clone --branch nemo-v2 --depth 1 https://github.com/AI4Bharat/NeMo.git ~/ai4bharat_nemo
```

## Configuration

`INDIC_NEMO_PATH`, `BHILI_ENABLE`, `BHILI_NEMO_PATH`, `HF_TOKEN`, `PORT` — see
`.env.example` here, and `model-server/.env.example` for what Compose passes in.

## GPU

An NVIDIA GPU is strongly recommended; CPU works but is far too slow for a live
call. VRAM depends on the checkpoint and batch settings — measure on staging
rather than trusting a number here. On the H200 this and Indic Parler together
draw roughly 12 GB.
