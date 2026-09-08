# Changelog

All notable changes to VoicEra are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project intends to follow [Semantic Versioning](https://semver.org/)
once it cuts a release.

> **No tagged release yet.** Everything below is the work in progress on `dev`.
> Dates and grouping are derived from the commit history, not from a release.

## [Unreleased]

This entry covers the rebuild of VoicEra from the earlier
`voicera_mono_repository` into the current monorepo. It is a restructure rather
than an increment: services were renamed, the data store was replaced, and
several subsystems are new.

### Added

- **Provider registry** (`apps/providers`) — a self-describing catalogue of STT,
  TTS, and LLM vendors. Providers register themselves with decorators; a
  discriminated union in `factory.py` and a readable schema dump in `schema.py`
  drive the `/configuration/*` endpoints, so adding a vendor never means editing
  a central if/elif chain. 22 cloud vendors, the Bhashini (STT/TTS) and Kenpath
  (LLM) adapters, and two local providers — `indic_orpheus` (TTS) and
  `indic_nemotron` (STT) — reached through the model server gateway instead of
  stored credentials. Kenpath and its Bharat Vistaar variant detect their own
  "goodbye" end-of-call signal in streamed LLM text, strip it before TTS speaks
  the chunk, and end the pipeline — a provider-specific mechanism alongside the
  config-driven `automatic_call_ending`.
- **Provider credentials** (`ProviderAuth`) — provider-level credentials stored
  per organisation and Fernet-encrypted at rest with
  `PROVIDER_AUTH_ENCRYPTION_KEY`. Members see secrets masked; only secret fields
  are stored.
- **Outbound campaigns** — CSV upload and source sync, an event-driven
  orchestrator on Redis pub/sub, ARQ batch execution, a from-number pool,
  configurable retry policy, calling-hour schedules, a circuit breaker that
  pauses a campaign when the failure rate crosses a threshold, progress
  reporting, and redial.
- **Call concurrency and rate limiting** — organisation- and campaign-scoped
  slots held in Redis, acquired through atomic Lua scripts, with stale-slot
  reclamation.
- **Redis-backed job queue** — an ARQ worker and a campaign orchestrator, both
  built from the API image and distinguished only by their command.
- **Plivo telephony provider**, alongside Vobiz, behind a provider-agnostic
  registry that dispatches clients, answer XML, and frame serializers.
- **Model server** — every self-hosted model behind one gateway on `:8100`, with
  three fixed slots (STT, TTS, LLM) filled by model folders named in `.env`.
  Ships `indic-conformer` and `indic-transcribe` for STT, `indic-parler`,
  `orpheus`, and `indic-mio` for TTS, and `qwen3.5-4b` for LLM. The
  `indic_orpheus` provider catalog moved to Orpheus's v2 voice roster — 24
  languages (up from 17) and a new set of lowercase style names replacing the
  old all-caps ones, default style `news`.
- **Real-time transcription** — both STT models standardised on `WS /v1/realtime`
  with incremental partial transcripts.
- **Knowledge base (RAG)** — PDF ingestion, chunking, embeddings, and per-org
  Chroma collections, retrievable as an LLM tool or as prepended context.
- **Call artifacts** — transcripts and recordings written to MinIO at call end,
  referenced by `minio://` URIs on the call log and served through authenticated
  API proxy routes.
- **Web call registration** — browser websocket sessions now get a
  `call_type: web` CallLog, so they produce transcripts and recordings under the
  same MinIO paths as telephony calls. The runtime registers one on connect via
  `POST /api/v1/calls/web`, or reuses a `call_id` passed on the WebSocket URL.
- **Agent behaviour controls** — hold messages, user-online detection, idle
  handling, barge-in tuning, and automatic call ending via an LLM tool.
- **Custom variables** in agent configuration, substituted into prompts.
- **Inbound call registration** with idempotent handling of repeated provider
  callbacks, plus number backfill for unknown callers.
- **Call log pagination and organisation filtering.**
- **Documentation** — Mintlify source under `docs/`, with site navigation in
  `docs.json` at the repository root. A hosted docs site is not published yet.
- **Dashboard** — a Next.js web console (`frontend/`) added to the Compose
  stack as the `frontend` service, port `3000`.

### Changed

- **Data store: MongoDB replaced by FerretDB 2.7** on PostgreSQL with the
  DocumentDB extension. The MongoDB wire protocol is unchanged, so `pymongo`
  still works, but the host port is now `27018` (`27017` inside the container)
  and `MONGODB_AUTH_SOURCE` must be empty.
- **Services renamed and restructured** — `voicera_backend` became `apps/api`,
  and `voice_2_voice_server` became `apps/runtime`.
- **Configuration consolidated** into a single root `.env`, replacing the
  per-service environment files. The model server keeps its own `model-server/.env`.
- **Voice pipeline decomposed** from one module into composable pieces —
  `pipeline`, `factory`, `config`, `lifecycle`, `hold`, `idle`, `call_ending`,
  `audio`, `runners`, and event handlers.
- **Telephony extracted** into `apps/telephony`, shared by the API and the
  runtime, with per-provider modules and no provider branching in the facades.
- **Provider configuration unified** — separate Auth, Settings, and Config
  layers per vendor, with `UserConfig` renamed to `AgentConfig`.
- **Container and volume naming** standardised on the `voicera_oss_*` prefix.
- **Runnable scripts consolidated** into `scripts/`, all invoked from the
  repository root, with a `Makefile` in front of them (`make application-up`,
  `make model-server-setup`, etc.). The model server's own `setup.sh`/`stop.sh`
  moved out of `model-server/` to `scripts/start-model-server.sh` and
  `scripts/stop-model-server.sh`; the root `start_docker.sh`/`stop_services.sh`
  were renamed to `start-application-services.sh`/`stop-application-services.sh`.

### Removed

- The three separate AI4Bharat and LLM server deployments, replaced by the
  single slot-based model server.
- The Integrations credential model, replaced by `ProviderAuth`.
- Hugging Face and MiniMax provider implementations.

### Known gaps

- No tagged release, and no CI.
- A real call through the runtime to a self-hosted model server has not been
  verified end to end. The LLM slot has never been built or started, and has
  no `apps/providers/local/` provider wiring it up yet — a self-hosted LLM
  still requires routing a cloud `openai` config through a custom `base_url`.
- `call_timeout_seconds` and `language.secondary` are accepted by the API but
  not read by the runtime.
- The campaign orchestrator cannot run with more than one replica.

[Unreleased]: https://github.com/COSS-India/voicera/commits/dev
