# VoicEra Runtime

> Telephony answer webhook and the Pipecat voice pipeline — STT → LLM → TTS.

[![Port](https://img.shields.io/badge/port-7860-blue.svg)](http://localhost:7860/health)
[![Pipecat](https://img.shields.io/badge/Pipecat-voice%20pipeline-8B5CF6.svg)](https://github.com/pipecat-ai/pipecat)

FastAPI service on **port 7860** that:

1. Serves **`GET|POST /answer?agent_id=&org_id=`** for **telephony** agents → Stream XML (provider from `agent.telephony.provider`)
2. Accepts **`WS /agent/{org_id}/{agent_id}`** for both agent types:
   - **telephony** — provider media stream (`vobiz` / `plivo` frame serializer)
   - **websocket** — browser clients via Pipecat protobuf/RTVI frames

The runtime loads agent config and provider auth from the VoicEra API (port 8000)
and runs a Pipecat pipeline (STT → LLM → TTS) via `apps.providers`.

## Agent modes

| `agent_category` | `/answer` | `/agent` WebSocket | Frame serializer |
|----------------|-----------|--------------------|------------------|
| `telephony` | Yes — returns provider Stream XML | Expects telephony `start` event | `create_frame_serializer(provider, ...)` |
| `websocket` | No — returns 400 | Direct browser connection | `ProtobufFrameSerializer` (RTVI) |

### Telephony agents

Answer and hangup URLs are provisioned by the API when the agent is created:

```
{VOICE_SERVER_BASE_URL}/answer?agent_id={agent_id}&org_id={org_id}
```

The provider (`vobiz` or `plivo`) comes from the agent document — the runtime does
not default to a single vendor.

### Websocket agents

Frontend clients connect directly to:

```
wss://{VOICE_SERVER_BASE_URL}/agent/{org_id}/{agent_id}
```

Use the Pipecat JS client with `@pipecat-ai/websocket-transport` and protobuf
frames. No `/answer` webhook is involved.

**Call logs and artifacts:** On connect, the runtime registers a `call_type: web`
CallLog via `POST /api/v1/calls/web` (auto-create) or reuses an existing
`call_id` from the query string. Transcripts and recordings are stored under the
same MinIO paths as telephony calls.

**Auto-create (default):**

```
wss://{host}/agent/{org_id}/{agent_id}
```

**Pre-create (optional):** Register a session first, then pass `call_id`:

```http
POST /api/v1/calls/web
{ "agent_id": "...", "custom_variables": { "name": "Jane" } }
→ { "call_id": "..." }
```

```
wss://{host}/agent/{org_id}/{agent_id}?call_id={call_id}
```

## Run (Docker)

From the repo root:

```bash
cp .env.example .env   # edit secrets + VOICE_SERVER_BASE_URL
./scripts/start_docker.sh
```

This starts API, runtime, FerretDB, and MinIO. Runtime is available at
`http://localhost:7860` (or `RUNTIME_HOST_PORT` from `.env`).

## Smoke tests

```bash
curl -s http://localhost:7860/health

curl -s -X POST \
  'http://localhost:7860/answer?agent_id=YOUR_AGENT_ID&org_id=YOUR_ORG_ID'
```

Expect XML with a `<Stream …>` URL derived from `VOICE_SERVER_BASE_URL`
(e.g. `wss://voice.example.com/agent/YOUR_ORG_ID/YOUR_AGENT_ID`).

Browser live test (wizard or custom client) — same route as telephony, the runtime
dispatches by the agent's `agent_category`:

```
ws://localhost:7860/agent/{org_id}/{agent_id}
```

`org_id` is always passed per-request in telephony URLs — there is no global default.

## Live calls

Your telephony provider must reach your public answer and WebSocket URLs. Set
`VOICE_SERVER_BASE_URL` in the root `.env` to your public host (e.g.
`https://voice.example.com`). The API uses the same variable when creating
telephony agents.

## Call artifacts (MinIO + API proxy)

For **telephony** and **websocket** calls, transcripts and recordings are uploaded
to MinIO under **`call_id`**:

```
voicera-calls/{org_id}/{call_id}/transcript.txt   # uploaded at call end
voicera-calls/{org_id}/{call_id}/recording.wav    # uploaded at call end
```

The runtime stores **`minio://`** URIs on the CallLog via `PATCH /api/v1/calls/{call_id}`
(bot JWT). Clients fetch artifacts through authenticated API proxy routes:

```
GET /api/v1/calls/{call_id}/recording
GET /api/v1/calls/{call_id}/transcript
```

Browse raw objects in the MinIO console at `http://localhost:9001`.

## Env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `VOICE_SERVER_BASE_URL` | — | Public base URL for answer + WebSocket URLs |
| `SAMPLE_RATE` | `8000` | Telephony audio sample rate |
| `WEBSOCKET_SAMPLE_RATE` | `16000` | Browser WebSocket audio sample rate |
| `API_BASE_URL` | `http://localhost:8000/api/v1` | VoicEra API for agents + auth |
| `INTERNAL_API_KEY` | — | Bot JWT minting for runtime → API |

All variables live in the repository root [`.env.example`](../../.env.example).
Inside Docker Compose, `API_BASE_URL` and `MINIO_ENDPOINT` are overridden for
in-network service discovery (`http://api:8000/api/v1`, `minio:9000`).

---

Full documentation: [Runtime service](../../docs/developer/services/runtime.md) · [Voice pipeline](../../docs/guides/concepts/voice-pipeline.md) · [WebSocket API](../../docs/api-reference/websocket-api.md)
