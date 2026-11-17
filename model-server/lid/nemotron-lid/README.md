# nemotron-lid (model-server slot)

Spoken language ID for nine Indic languages: frozen Nemotron encoder + linear
probe. **Identify only** — VoicEra mid-call switching posts WAV to
`POST /identify`; there is no streaming ASR in this slot.

| Language | Code |
|----------|------|
| Bengali, Gujarati, Hindi, Kannada, Malayalam, Marathi, Punjabi, Tamil, Telugu | `bn gu hi kn ml mr pa ta te` |

English is **not** in the probe.

## Setup

```bash
cd model-server

# Weights (pick one):
# A) download into this slot (~2.4 GB)
sh lid/nemotron-lid/fetch.sh
# B) reuse the same .nemo as indic-nemotron STT (same SHA256)
#    LID_MODELS_DIR=./stt/indic-nemotron/models/indic-asr-nemotron-600m

# model-server/.env
LID_MODEL=nemotron-lid
COMPOSE_PROFILES=stt,tts,lid   # include lid with your other slots

# from repo root:
./scripts/start-model-server.sh
```

Health: `GET http://localhost:8100/lid/health`  
Identify (via gateway): `POST http://localhost:8100/v1/lid/identify` (multipart field `audio`)

## Runtime (VoicEra app)

[`docker-compose.yaml`](../../docker-compose.yaml) sets:

```bash
NEMOTRON_LID_URL=http://host.docker.internal:8100/v1/lid
```

Agent Call details → **LID (audio detection)** (`behaviour.language_switching_mode: lid`) with 2+ languages.

## Notes

- Weights file: `indic_nemotron_v1_1_sft_600k_lr1-averaged-40k.nemo` (HF `vedantahatti/nemotron-lid`).
- Package under `nemotron_lid/` is vendored from `voice_era_repos/nemotron-lid`; deployment knobs live only in `compose.extra.yml`.
- Docker bind-mounts must see a **real** `.nemo` file (host symlinks that point outside the mount break inside the container).
