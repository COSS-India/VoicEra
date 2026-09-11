---
title: Testing
description: Running the VoicEra test suites.
---

VoicEra has five test suites, one per package. Each lives inside the code it covers — there is no top-level `tests/` directory and no aggregate runner. This page tells you how to run each, what it needs, and what breaks if you skip it.

<Note>
There is **no CI**. The repository has no `.github/` directory, no workflows, and no pre-commit hooks. Nothing runs on a push. Every check on this page is one you run yourself, before opening a pull request.
</Note>

## The five suites

| Suite | Modules | Covers | Needs Docker |
| --- | --- | --- | --- |
| `apps/api/tests` | 20 | Auth, agents, telephony provisioning, campaigns, knowledge base, call artifacts, secret encryption. | No |
| `apps/runtime/tests` | 7 | Route dispatch, prompt substitution, hold messages, call ending, knowledge injection, call metrics, AI service factory. | No |
| `apps/telephony/tests` | 6 | Registry, clients, answer XML, serializers, webhooks, catalog schema. | No |
| `apps/providers/tests` | 5 | The provider registry and catalog dump, plus availability, capabilities, and scoped settings. | No |
| `model-server/tests` | 27 | Catalogue, gateway streaming, slot behaviour, audio parity, KV page allocation. | Only `test_model_switching` |

None of them needs a database, a GPU, or a network. Five model-server modules shell out to `docker compose config`.

Run one at a time (see the warning below), a healthy tree looks like this:

| Suite | Result |
| --- | --- |
| `apps/api/tests` | 126 passed, 1 skipped — the skip is the opt-in telephony integration module |
| `apps/runtime/tests` | 40 passed |
| `apps/telephony/tests` | 65 passed, 2 failed — see [the Plivo serializer defect](#appstelephony) |
| `apps/providers/tests` | 69 passed |
| `model-server/tests` | 241 passed, 64 skipped, 1 failed — see the Docker and NOT VERIFIED notes below |

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
pip install -r apps/api/requirements.txt pytest
pytest apps/api/tests -v
```

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

`tests/requirements-dev.txt` is deliberately small: `pytest`, `pytest-asyncio`, `httpx`, `numpy`, `fastapi`, `uvicorn`, `ruff`, `websockets`, plus the three `grpcio` packages that exercise `stt/_grpc/`. No torch, no NeMo, no CUDA. `tests/pytest.ini` sets `asyncio_mode = auto`, so async tests need no decorator.

<Note>
Add `pyyaml` as well. Thirteen modules `import yaml` to read `models.yaml` and the compose files, but `requirements-dev.txt` does not list it, so a clean virtualenv built from that file alone fails at collection with `ModuleNotFoundError: No module named 'yaml'`.
</Note>

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

`test_registry.py` asserts the registered set is exactly `{"vobiz", "plivo"}` and that the lazy serializer load works. `test_xml.py` pins the answer XML per sample rate — the string most likely to be silently wrong, because malformed XML produces a call that connects and then goes quiet.

<Note>
Two tests in `test_serializers.py` currently **fail**: `test_create_frame_serializer_known_providers[plivo]` and `[Plivo]`, with `ValueError: auto_hang_up is enabled but missing required parameters: auth_id, auth_token`.

This is a real defect, not a stale test. Pipecat's `PlivoFrameSerializer` defaults `auto_hang_up` to `True` and then requires `auth_id` and `auth_token`, but `apps/telephony/providers/plivo/serializer_service.py` passes neither — and neither does the runtime callsite in `apps/runtime/services/pipecat/runners.py`, so the serializer raises before any Plivo call can start. Vobiz is unaffected because `VobizFrameSerializer.InputParams` sets `auto_hang_up=False` explicitly. The fix is to do the same for Plivo, since the runtime ends calls itself and holds no Plivo API credentials at that point.
</Note>

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
