---
title: Repository layout
description: A map of the VoicEra monorepo.
---

Where everything lives, what owns what, and which files are placeholders you should not read anything into.

<Note>
For the runtime relationship between these directories — which process talks to which — read [Architecture](../../guides/concepts/architecture) first. This page is about the tree on disk.
</Note>

## Top level

```text
VoicEra/
├── apps/                  Application code — four Python packages
├── frontend/              Next.js dashboard — the web console
├── model-server/          Optional self-hosted STT, TTS, and LLM stack
├── scripts/               start/stop scripts for the application stack and the model server
├── docs/                  This documentation (Mintlify)
├── docker-compose.yaml    The whole local stack
├── .env.example           The single environment template
├── docs.json              Mintlify navigation, tabs, and redirects
├── README.md              Short pointer to the Docker quick start
├── CHANGELOG.md           Keep a Changelog history
├── CONTRIBUTING.md        Contributor entry point
├── SECURITY.md            Vulnerability reporting policy
├── CODE_OF_CONDUCT.md     Community standards and enforcement
├── LICENSE                Apache 2.0
├── Makefile               Wrappers for the start/stop scripts — `make help` lists them
├── pyproject.toml         Placeholder — empty
└── __init__.py            Empty; makes the checkout importable as a package
```

| Path | Role |
| --- | --- |
| `docs.json` | Mintlify site config: tabs (Guides, Developer, API Reference), groups, and redirects. |
| `docker-compose.yaml` | Ten services: `postgres`, `ferretdb`, `api`, `arq-worker`, `campaign-orchestrator`, `runtime`, `frontend`, `redis`, `minio`, `minio-init`. Container and volume names are prefixed `voicera_oss_`; the network is `app-network`. |
| `.env.example` | The one environment template. Copy it to `.env` at the root. See [Environment variables](../reference/environment-variables). |
| `scripts/start-application-services.sh` | Creates a root `.env` if one doesn't exist, generating `SECRET_KEY`, `INTERNAL_API_KEY`, and `PROVIDER_AUTH_ENCRYPTION_KEY` if missing, then starts the stack. Run it via `make application-up` rather than calling it directly or using a bare `docker compose up`. |
| `scripts/stop-application-services.sh` | Stops the stack. |
| `Makefile` | Thin wrappers over those scripts and the Compose commands: `application-up`, `application-down`, `restart`, `application-logs`, `application-ps`, the five `model-server-*` equivalents, and `down-all`. Run `make help` for the list. |

## apps

Four packages under one namespace. `apps/__init__.py` is empty and exists so `apps.providers` and `apps.telephony` are importable from the repository root.

```text
apps/
├── __init__.py
├── api/          FastAPI REST surface (also the ARQ worker and orchestrator)
├── runtime/      Answer webhook and the Pipecat audio pipeline
├── providers/    STT, TTS, and LLM vendor registry
├── telephony/    Vobiz and Plivo clients, answer XML, frame serializers
└── schemes/      Empty — see below
```

### apps/api

```text
apps/api/
├── Dockerfile          Builds api, arq-worker, and campaign-orchestrator
├── README.md           Route tables and auth model
├── requirements.txt
├── app/
│   ├── main.py         FastAPI application
│   ├── config.py       Pydantic BaseSettings; pins the root .env
│   ├── auth.py         JWT and X-API-Key dependencies
│   ├── database.py     FerretDB client
│   ├── database_init.py
│   ├── routers/        Thin HTTP layer under /api/v1
│   ├── services/       Business rules — agents, campaigns, concurrency, RAG
│   ├── models/         Pydantic documents and request/response schemas
│   ├── constants/      Campaign and call constants
│   ├── rag/            Chroma ingest and retrieval
│   ├── storage/        MinIO helpers
│   ├── tasks/          ARQ job definitions, including WorkerSettings
│   └── utils/
└── tests/              20 test modules plus conftest.py
```

One package, **three containers**. `api`, `arq-worker`, and `campaign-orchestrator` all build from `apps/api/Dockerfile` and differ only in their `command:`. See [Workers and orchestrator](../services/workers).

### apps/runtime

```text
apps/runtime/
├── Dockerfile          Sets PYTHONPATH=/app
├── requirements.txt    FastAPI, Pipecat 1.8.1, MinIO
├── app.py              FastAPI app plus a main() entry point
├── constants.py        os.getenv at call time, not at import
├── routes/             health, telephony (/answer), agent (WS)
├── services/
│   ├── agent_routing.py
│   ├── backend.py            Fetches agent config and credentials from the API
│   ├── ai_service_factory.py Builds STT, TTS, and LLM from apps.providers
│   ├── pipecat/              The pipeline — 9 modules + events/, metrics/, termination/
│   ├── knowledge/            RAG context injection
│   └── storage/              Call artifacts to MinIO
└── tests/              7 test modules plus conftest.py
```

### apps/providers

```text
apps/providers/
├── base.py         Kind and ProviderType enums, Auth/Settings/Config bases
├── registry.py     @register_stt / @register_tts / @register_llm, load_providers()
├── factory.py      Discriminated unions from the registry, create_*_service dispatch
├── schema.py       provider_schemas() and configuration_defaults() catalog dump
├── languages.py    Canonical language ids and language_schema_extra()
├── readme.md
├── cloud/          22 vendor folders → provider_type=cloud
├── adapters/       bhashini · kenpath → provider_type=adapter
├── local/          indic_nemotron (STT) · indic_orpheus (TTS) → provider_type=local
└── tests/          5 test modules
```

Every STT/TTS vendor folder is three files: `catalog.py` (with `*_CAPABILITIES`), `config.py`, `service.py`. LLM-only vendors may keep an empty stub `languages.py`. See [Adding an AI provider](adding-a-provider).

### apps/telephony

```text
apps/telephony/
├── base.py             Kind, Credentials, ApiResult, shared httpx helpers, config bases
├── registry.py         @register_client / @register_answer_xml / @register_frame_serializer
├── xml.py              build_answer_stream_xml dispatcher
├── serializers.py      create_frame_serializer dispatcher (needs pipecat)
├── calls.py            initiate_outbound dispatcher
├── webhooks.py         Provider webhook parsing
├── schema.py           provider_schemas / configuration_telephony
├── readme.md
├── scripts/print_schemas.py
├── providers/
│   ├── vobiz/          10 files
│   └── plivo/          10 files
└── tests/              6 test modules
```

The package-root `xml.py`, `calls.py`, and `serializers.py` are dispatch facades. They contain no provider `if`/`elif` chains and must not grow any. See [Adding a telephony provider](adding-a-telephony-provider).

<Note>
`apps/telephony/README.md` documents the package's public API and is current.
</Note>

## model-server

A separate Docker Compose stack with its own `.env`, run only if you want to host models yourself.

```text
model-server/
├── README.md
├── compose-files.sh
├── compose.model-server.yml       The stack
├── compose.mps.yml                NVIDIA MPS overlay
├── compose.shared-hf-cache.yml    Shared HuggingFace cache overlay
├── models.yaml                    The catalogue
├── ruff.toml                      The only lint config in the repository
├── gateway/                       One published port; routes to the slots
├── stt/                           indic-conformer, indic-transcribe
├── tts/                           indic-mio, indic-parler, orpheus
├── llm/                           qwen3.5-4b
├── tests/                         27 test modules plus stubs
└── hindi.wav                      Fixture for the GPU smoke script
```

Three **slots** — STT, TTS, LLM — each filled by naming a folder in `STT_MODEL`, `TTS_MODEL`, or `LLM_MODEL`. See [Model server overview](../model-server/overview).

## scripts

Four shell scripts, all meant to be run from the repository root.

| Script | What it does |
| --- | --- |
| `start-application-services.sh` | Creates or updates the root `.env`, generating the three secrets if they are missing, then brings the application stack up detached. |
| `stop-application-services.sh` | Brings the application stack down. |
| `start-model-server.sh` | Runs the model-server setup: picks a model per slot, fetches weights, builds images, and starts the model-server stack. See [Model server overview](../model-server/overview). |
| `stop-model-server.sh` | Stops the model-server stack. |

## Where tests live

Tests sit inside the package they cover. There is no top-level `tests/` directory.

| Suite | Modules | Covers |
| --- | --- | --- |
| `apps/api/tests` | 18 | Auth, agents, telephony provisioning, campaigns, knowledge base, call artifacts. |
| `apps/runtime/tests` | 5 | Routing, prompt substitution, hold, call ending, knowledge. |
| `apps/telephony/tests` | 6 | Registry, clients, XML, serializers, webhooks, schema. |
| `apps/providers/tests` | 1 | The registry and the catalog dump. |
| `model-server/tests` | 20 | Catalogue, gateway streaming, slot behaviour, audio parity. |

Full instructions in [Testing](testing).

## Files that are intentionally empty

Several files exist so tooling and GitHub find them, but hold no content yet. Do not infer a workflow from their presence.

| File | State | What this means |
| --- | --- | --- |
| `pyproject.toml` | Empty | The project is **not** pip-installable. There is no `pip install -e .`, no build backend, and no tool configuration. Dependencies come from `apps/<app>/requirements.txt`. |
| `apps/schemes/__init__.py` | Empty | `apps/schemes/` contains nothing but this empty file. It is not imported anywhere. |
| `apps/runtime/services/pipecat/termination/__init__.py` | Empty | The `termination/` package holds nothing but this empty file. Nothing imports it. |
| `__init__.py` (root) | Empty | Makes the checkout itself importable as a package, which lets pytest import the tree as `voicera.apps.providers` when the parent directory is on `sys.path`. `apps/providers/registry.py` resolves vendor roots from `__package__` rather than a hardcoded `apps.providers` prefix for exactly this reason. |

There is also **no `.github/` directory**, and therefore no CI, no workflows, no issue templates, and no pull-request template. Nothing runs automatically on a push. Every check is something you run locally before opening a pull request.

<Note>
Because there is no CI, a green local run is the only signal a change has. Run the relevant [test suites](testing) and `ruff check .` in `model-server/` yourself.
</Note>

## Related

* [Local setup](local-setup)
* [Testing](testing)
* [Architecture](../../guides/concepts/architecture)
* [Services overview](../services/index)
