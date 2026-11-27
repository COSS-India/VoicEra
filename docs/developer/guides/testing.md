---
title: Testing
description: Running the VoicEra test suites.
---

VoicEra has five test suites, one per package. Each lives inside the code it covers — there is no top-level `tests/` directory and no aggregate runner. This page tells you how to run each, what it needs, and what breaks if you skip it.

## Continuous integration

Three GitHub Actions workflows run on the repository. There are no pre-commit hooks.

| Workflow | Runs on | What it checks |
| --- | --- | --- |
| [`tests.yml`](https://github.com/COSS-India/VoicEra/blob/staging/.github/workflows/tests.yml) | Every push to `main`, `staging` and `dev`, and every pull request | The five pytest suites on this page, one job each, with line coverage |
| [`standards.yml`](https://github.com/COSS-India/VoicEra/blob/staging/.github/workflows/standards.yml) | Every push to `main`, `staging` and `dev`, and every pull request | OpenAPI 3.1, BCP 47 language tags, hadolint, the Compose Specification, and Trivy dependency and secret scanning |
| [`mintlify-docs-check.yml`](https://github.com/COSS-India/VoicEra/blob/staging/.github/workflows/mintlify-docs-check.yml) | Pull requests that touch `docs/`, and pushes to `main` that touch `docs/` | The documentation site builds |

`tests.yml` runs each suite in its own job, for the import reason explained [below](#running-them). Each job uploads a JUnit report and a Cobertura coverage report as artifacts, and writes the line-coverage figure to the run summary. A failure in one suite does not cancel the others.

Trivy in `standards.yml` reports only (`exit-code: "0"`), so a finding does not fail the build yet.

Some tests are known to fail and are skipped in CI by name. They are listed under [Known failures](#known-failures). Every other test must pass, so a new failure turns the run red. Run the suites yourself before opening a pull request anyway, because CI covers only what the suites test.

## The five suites

| Suite | Modules | Covers | Needs Docker |
| --- | --- | --- | --- |
| `apps/api/tests` | 20 | Auth, agents, telephony provisioning, campaigns, knowledge base, call artifacts, secret encryption. | No |
| `apps/runtime/tests` | 7 | Route dispatch, prompt substitution, hold messages, call ending, knowledge injection, call metrics, AI service factory. | No |
| `apps/telephony/tests` | 6 | Registry, clients, answer XML, serializers, webhooks, catalog schema. | No |
| `apps/providers/tests` | 5 | The provider registry and catalog dump, plus availability, capabilities, and scoped settings. | No |
| `model-server/tests` | 27 | Catalogue, gateway streaming, slot behaviour, audio parity, KV page allocation. | Only `test_model_switching` |

None of them needs a database, a GPU, or a network. Five model-server modules shell out to `docker compose config`.

Run one at a time (see the warning below), the `staging` branch on 27 Nov 2026 gives these results. They are the same as CI, with the known failures skipped:

| Suite | Result | Line coverage |
| --- | --- | --- |
| `apps/api/tests` | 285 passed, 12 skipped, 1 known failure. The skips are two opt-in integration modules: live telephony (1 test, `RUN_TELEPHONY_INTEGRATION=1`) and the audit-log event store (11 tests, `EVENTLOG_TEST_MONGODB_URI`). | 59% |
| `apps/runtime/tests` | 264 passed, 3 known failures | 79% |
| `apps/providers/tests` | 107 passed, 1 known failure | 54% |
| `apps/telephony/tests` | 189 passed, 2 known failures | 81% |
| `model-server/tests` | 654 passed, 56 skipped, 2 known failures. See the Docker and NOT VERIFIED notes below. | 84% |

The counts move as tests are added. Coverage is lines executed by the suite, not a measure of how well behaviour is checked.

## Known failures

These nine tests fail on `staging` today. In each case the code changed and the test was not updated, so the test is out of date rather than the code being broken. `tests.yml` skips them by name with `--deselect`, and each has a comment there saying why. When you fix one, delete its line from `tests.yml` in the same pull request.

| Suite | Test | Why it fails |
| --- | --- | --- |
| api | `test_configuration_routes.py::test_tts_setting_includes_scoped_tree` | The Sarvam catalogue moved from `bulbul:v2` to `bulbul:v3`. The test still expects `bulbul:v2`. |
| providers | `test_settings_by_model_language.py::test_sarvam_voice_options_split_by_model` | Same `bulbul:v2` to `bulbul:v3` change. |
| runtime | `test_orpheus_sample_rate_label.py` (three tests) | The Indic Orpheus TTS service no longer pins its sample rate to 24 kHz the way the tests expect. |
| telephony | `test_schema.py::test_vi_secrets_and_dni_flow_fields` and `::test_telephony_settings_and_auth_split` | The Vodafone Idea schema gained `pull_username` and `pull_password`. The expected field sets were not updated. |
| model-server | `test_env_example.py::test_every_variable_compose_reads_is_documented` | The compose files read variables that `.env.example` does not document (`ORPHEUS_*`, `NEMOTRON_*`, `STT_GRPC_*` and others). |
| model-server | `test_grpc_facade.py::test_the_facade_folder_is_hidden_from_the_model_menu_and_the_catalogue` | The test looks for `model-server/setup.sh`, which was deleted. |

Before treating any of these as stale, check the runtime Orpheus case: if callers hear audio at the wrong speed, the old test was right and the code is wrong.

## Running them

Every command below assumes you are at the repository root and the root is on `PYTHONPATH`:

```bash
export PYTHONPATH="$PWD"
```

`apps/providers`, `apps/telephony`, and `apps/runtime` import each other as `apps.*`, so this is not optional. See [Local setup](local-setup#the-pythonpath-and-the-apps-namespace).

<Note>
Run the suites in **separate `pytest` invocations**, one per package. Passing them all to a single command fails at collection with `ModuleNotFoundError: No module named 'app.auth'` and similar: `apps/api` imports a top-level `app.*` package via its `conftest.py`, and `model-server/tests` puts its own tree on `sys.path`, so whichever is collected first claims the name. Each suite passes on its own.
</Note>

### Providers and telephony

Both suites need the runtime requirements as well as the API ones, plus `pytest-asyncio`:

```bash
pip install -r apps/api/requirements.txt -r apps/runtime/requirements.txt pytest pytest-asyncio
pytest apps/providers/tests apps/telephony/tests -v
```

The API requirements alone are not enough. `apps/telephony/providers/plivo/serializers.py` and `.../vobiz/serializers.py` both import `pipecat.serializers.plivo` at module level, and the Bhashini provider tests reach the Pipecat TTS base classes, so `pytest` fails at collection with `ModuleNotFoundError: No module named 'pipecat'` without it. `pytest-asyncio` is needed too — several modules use `@pytest.mark.asyncio`, and without the plugin those tests fail rather than skip.

### API

```bash
pip install -r apps/api/requirements.txt pytest pytest-asyncio
export MINIO_SECRET_KEY=test-only
pytest apps/api/tests -v
```

`pytest-asyncio` is required: the campaign dispatcher, status processor and phone-number modules use `@pytest.mark.asyncio`, and without the plugin about 30 tests fail. `MINIO_SECRET_KEY` must be set to any non-empty value. The MinIO client refuses an empty secret, and the OBD report tests create one without patching it. They never connect to a real MinIO. Leave `SECRET_KEY` and `INTERNAL_API_KEY` unset; the runtime routing tests fail if they are present.

`apps/api/tests/conftest.py` puts both `apps/api` (for `app.*`) and the repository root (for `apps.*`) on `sys.path`, so this works from any directory. Routes are exercised through FastAPI's `TestClient` against in-memory stores and `unittest.mock.patch`, not a live FerretDB.

One module is opt-in. `test_agent_telephony_integration.py` places real calls against real provider credentials and is skipped unless you ask for it:

```bash
RUN_TELEPHONY_INTEGRATION=1 \
TEST_ORG_ID=<your-org-id> \
VOICE_SERVER_BASE_URL=https://voice.example.com \
INTERNAL_API_KEY=<key> \
pytest apps/api/tests/test_agent_telephony_integration.py -q
```

That needs the API stack up, FerretDB reachable, and provider credentials stored. It costs money at the telephony vendor. Leave it off unless you are changing provisioning.

### Runtime

```bash
python -m venv .venv-runtime
source .venv-runtime/bin/activate
pip install -r apps/api/requirements.txt -r apps/runtime/requirements.txt pytest pytest-asyncio
export PYTHONPATH="$PWD"
pytest apps/runtime/tests -v
```

`pytest-asyncio` is not optional here: `test_hold.py` and `test_call_metrics_writer.py` are `@pytest.mark.asyncio` coroutines, and without the plugin pytest reports `PytestUnknownMarkWarning` and fails them.

A separate virtualenv is worth it — `apps/runtime/requirements.txt` pulls in `pipecat-ai[deepgram,cartesia,openai,silero,websocket]==1.8.1`, which the other suites neither need nor want.

### Model server

```bash
cd model-server
pip install -r tests/requirements-dev.txt
pytest tests/ -v
ruff check .
```

`tests/requirements-dev.txt` is deliberately small: `pytest`, `pytest-asyncio`, `httpx`, `numpy`, `fastapi`, `uvicorn`, `ruff`, `websockets`, the three `grpcio` packages that exercise `stt/_grpc/`, and the packages the tests import directly: `pyyaml`, `aiohttp`, `soundfile`, `python-dotenv` and `python-multipart`. No torch, no NeMo, no CUDA. `tests/pytest.ini` sets `asyncio_mode = auto`, so async tests need no decorator.

`pytest.ini` also makes `model-server/tests` the rootdir, so test ids are relative to that folder (`test_catalogue.py::...`, not `tests/test_catalogue.py::...`). This matters when you pass `--deselect` or pick a single test.

## What needs Docker

Five model-server modules shell out to `docker compose config`: `test_model_switching.py`, `test_gpu_placement.py`, `test_grpc_facade.py`, `test_model_extras.py`, and `test_mps.py`. That subcommand only interpolates the compose files, so it needs the `docker` CLI but **no running daemon**. Four of them guard with `skipif(shutil.which("docker") is None)`; `test_grpc_facade.py` instead checks that `docker compose version` exits zero. On a machine with no Docker at all the whole model-server suite still runs; you just lose those modules' coverage.

<Note>
`test_gpu_placement.py::test_the_model_matches_real_compose` **fails** rather than skips on a Docker Desktop install. The `skipif` guard resolves `docker` on the full `PATH`, but the subprocess is then launched with a hardcoded `env={"PATH": "/usr/bin:/bin"}`. Docker Desktop puts the binary in `/usr/local/bin`, so the call raises `FileNotFoundError` before reaching the `returncode != 0` check that was meant to skip. Passing the inherited `PATH` through fixes it.
</Note>

No other suite touches Docker. The database-only Compose stack described in [Local setup](local-setup#database-only-compose) is for running the services by hand, not for testing.

## Why the model-server suite needs no GPU

The GPU stack is stubbed. `model-server/tests/stubs/` holds stand-ins for the three heavy imports:

```text
model-server/tests/stubs/
├── torch.py
├── nemo/collections/asr/models.py
└── inference/runner.py
```

`tests/conftest.py` puts that directory first on `sys.path`, ahead of any real package:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent / "stubs"))
sys.path.insert(0, str(ROOT / "gateway"))
```

Everything *else* is the real code — routing, batching, protocol handling, transport. As the suite's README puts it: the NeMo, torch, and Parler-runner layers are stubbed, so everything else is real. That is what makes it worth running on a laptop: it cannot tell you the model transcribes correctly, but it can tell you the gateway streams instead of buffering, that a client disconnect evicts the upstream request, and that the KV page allocator never hands one page to two calls.

Two scripts in that directory are **not** part of the suite because they need real models on a GPU:

| Script | Use |
| --- | --- |
| `smoke_gpu.py` | End-to-end round trip on the box: TTS speaks, STT transcribes it back. |
| `bench_tts.py` | Latency and real-time factor, sequential or at a chosen concurrency. |

## Fixtures and stubs

There are only two `conftest.py` files under `apps/`, and both do one narrow job.

`apps/api/tests/conftest.py` fixes imports:

```python
API_ROOT = Path(__file__).resolve().parents[1]
VOICERA_ROOT = Path(__file__).resolve().parents[3]

for path in (str(API_ROOT), str(VOICERA_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)
```

`apps/runtime/tests/conftest.py` stubs the Pipecat runners so route tests do not build a pipeline:

```python
_mock_runners = MagicMock()
_mock_runners.run_telephony_bot = AsyncMock()
_mock_runners.run_websocket_bot = AsyncMock()
sys.modules["apps.runtime.services.pipecat.runners"] = _mock_runners

from apps.runtime.app import app  # noqa: E402
```

The `sys.modules` assignment has to happen before `apps.runtime.app` is imported, which is why the import sits below it with a `noqa`. It also provides the shared `client` fixture wrapping `TestClient(app)`.

`apps/providers/tests` and `apps/telephony/tests` have no `conftest.py` at all. They rely on `PYTHONPATH` and on `load_providers()` doing its own discovery.

`model-server/tests/conftest.py` does more: the stub path insertion above, a `free_port()` helper, a `serve()` helper that runs an ASGI app on a background thread and waits for it to accept, and a `find_setup()` helper that locates `setup.sh` in either of the two places it has lived. Its comment on that last one is worth reading — hardcoding either path "turns a move into six silent skips: the suite stays green while the checks are simply not running."

## What each suite protects

### apps/providers

Five modules. `test_provider_schemas.py` tests the registry as a whole rather than each vendor: it pins the union member counts (13 STT, 15 TTS, 10 LLM), asserts every registered config has a creator and the reverse, and walks every provider asserting the catalog dump contains no `$defs`, `$ref`, or `anyOf`, that every secret field is marked and carries no `input_mode`, and that every language id emitted exists in the canonical `LANGUAGES` map. `test_availability.py`, `test_capabilities.py`, `test_scoped_settings.py`, and `test_settings_by_model_language.py` cover which providers are reachable, what each declares it can do, and how per-model and per-language settings resolve. See [Adding an AI provider](adding-a-provider#testing).

### apps/telephony

`test_registry.py` asserts the registered set includes the shipped telephony providers (`vobiz`, `plivo`, `vi`, `go2market`) and that the lazy serializer load works. `test_xml.py` pins the answer XML per sample rate — the string most likely to be silently wrong, because malformed XML produces a call that connects and then goes quiet. `test_serializers.py` checks that a frame serializer can be built for each provider. It includes Plivo, whose `serializer_service.py` now passes `auto_hang_up=False` so the serializer no longer asks for API credentials the runtime does not hold.

### apps/api

The broadest suite. `test_secret_crypto.py` covers Fernet encryption of `ProviderAuth`. `test_agent_telephony_service.py` and `test_agent_telephony.py` cover application provisioning and teardown on agent create, update, and delete. The campaign modules cover the dispatcher, the repository, CSV sync, and the status processor.

### apps/runtime

`test_routing.py` covers `/answer` and the `/agent` WebSocket handshake. `test_hold.py`, `test_call_ending.py`, and `test_prompt_substitution.py` cover pipeline behaviour that only shows up mid-call.

### model-server

`model-server/tests/README.md` has a full table. The shape of it: the early entries guard the audio itself (`test_stt_audio_parity`, `test_tts_request_parity`, `test_pcm_chunk_boundaries`), the middle ones guard the wiring between files (`test_catalogue`, `test_model_switching`, `test_setup_selection`), and the last ones guard the seam between the model server and the voice pipeline.

## Four model-server modules silently skip

<Note>
`test_llm_wiring.py`, `test_client_selection.py`, `test_tts_format_negotiation.py`, and `test_partial_transcripts.py` all locate the voice pipeline at `ROOT.parent / "voice_2_voice_server"` — a directory that **no longer exists**. Every test in those four modules therefore skips, and a skip does not fail a run.
</Note>

The paths are hardcoded at the top of each module:

```python
ROOT = Path(__file__).resolve().parent.parent          # → model-server/
V2V = ROOT.parent / "voice_2_voice_server"             # → voicera/voice_2_voice_server

pytestmark = pytest.mark.skipif(
    not V2V.is_dir(), reason="voice_2_voice_server not present in this checkout"
)
```

`voice_2_voice_server` was renamed to `apps/runtime` in the revamp. The directory those tests point at was never recreated, so `V2V.is_dir()` is `False` and 46 tests across the four modules never run. The exact number moves with the catalogue — `test_llm_wiring.py` parametrises over `deployable_llms()`.

The suite is honest about it. `conftest.py` installs a `pytest_terminal_summary` hook that prints a red **NOT VERIFIED** block after the summary line, naming what is unverified while that is true:

* every model marked `ready` can actually be named by an agent config
* the client decodes the audio format each TTS model declares
* partial transcripts still reach the caller mid-utterance

The comment above the hook explains why it exists: "A skip is invisible in a green summary line. That is the failure mode this hook exists for: the suite says '165 passed' while a quarter of what it claims to cover is not running."

These four modules should be repointed at `apps/runtime`. The specific paths they look for are `voice_2_voice_server/api/services.py`, `voice_2_voice_server/services/ai4bharat/stt.py`, and `voice_2_voice_server/services/ai4bharat/tts.py`, none of which map one-to-one onto the current runtime layout — the client selection logic now lives in `apps/providers` and the pipeline in `apps/runtime/services/pipecat/`. Repointing them is a real piece of work, not a path substitution.

<Note>
Until that is done, treat the model-server suite's pass count as covering the server side only. The seam between the model server and the voice pipeline is unverified, and that seam is where a mistake stays invisible until a live call drops.
</Note>

## Related

* [Local setup](local-setup)
* [Repository layout](repository-layout)
* [Contributing](contributing-guide)
* [Adding an AI provider](adding-a-provider)
* [Adding a telephony provider](adding-a-telephony-provider)
