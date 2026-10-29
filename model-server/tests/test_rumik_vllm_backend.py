"""The parts of tts/rumik-oss-1/vllm_backend.py that need no GPU to be wrong.

`check_memory_budget` exists because RUMIK_GPU_MEMORY_UTILIZATION is a fraction
of the card's TOTAL memory and its default, 0.12, was sized for a 143 GB H200.
Carried to a 24 GB card it reserves less than the weights, and vLLM then fails
deep in its profiler about KV cache blocks. The check turns that into a message
naming the knob and a value that would work -- and must never refuse the
configuration that is known to run.
"""
import asyncio
import enum
import importlib.util
import sys
import types
from pathlib import Path

import pytest

MODEL = Path(__file__).resolve().parent.parent / "tts" / "rumik-oss-1"
GIB = 1024 ** 3
WEIGHTS = int(6.76e9)  # the two shards, as fetched


@pytest.fixture(scope="module")
def backend():
    # vllm_backend imports its siblings as top-level `codec` and `config`.
    # Put the folder on sys.path only for the import, and drop the siblings
    # afterwards so no other test finds a bare `codec` module lying around.
    sys.path.insert(0, str(MODEL))
    try:
        spec = importlib.util.spec_from_file_location("rumik_vllm_backend",
                                                      MODEL / "vllm_backend.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(MODEL))
        for name in ("codec", "config"):
            sys.modules.pop(name, None)


def test_the_measured_h200_configuration_passes(backend):
    # ace-h200: 143 GB NVL at 0.12 loaded and allocated 10.06 GiB of KV cache.
    backend.check_memory_budget(total_bytes=143 * 10**9, fraction=0.12, weights=WEIGHTS)


def test_the_h200_default_on_a_24_gb_card_is_refused_with_a_working_value(backend):
    with pytest.raises(RuntimeError, match="RUMIK_GPU_MEMORY_UTILIZATION") as info:
        backend.check_memory_budget(total_bytes=24 * GIB, fraction=0.12, weights=WEIGHTS)
    suggested = float(str(info.value).split("Try RUMIK_GPU_MEMORY_UTILIZATION=")[1].split()[0])
    # The suggestion must itself pass, or the message sends the operator in a loop.
    backend.check_memory_budget(total_bytes=24 * GIB, fraction=suggested, weights=WEIGHTS)


def test_weights_are_measured_from_top_level_shards_only(backend, tmp_path):
    (tmp_path / "model-00001-of-00002.safetensors").write_bytes(b"x" * 10)
    (tmp_path / "model-00002-of-00002.safetensors").write_bytes(b"x" * 5)
    (tmp_path / "codec").mkdir()
    (tmp_path / "codec" / "model.safetensors").write_bytes(b"x" * 1000)
    assert backend.weights_bytes(str(tmp_path)) == 15


def test_a_repo_id_is_not_measured(backend):
    assert backend.weights_bytes("rumik-ai/rumik-oss-1") is None


# ------------------------------------------------------------- the token stream
#
# The first vLLM build lost ~27% of every utterance on hardware: 515-669 tokens
# yielded but only 73% of them decodable, against 100% on upstream's loop for
# the same prompt. The cause was ours. With detokenize=False, vLLM's CUMULATIVE
# output hands back its own token list and extends it in place from another
# task; the stream diffed `tokens[seen:]` then set `seen = len(tokens)`, which
# skipped everything appended while it was suspended in a `yield`. The fake
# below behaves the way vLLM does -- a live list for CUMULATIVE, fresh lists for
# DELTA, appends from a separate task -- so the old code fails this test.


class _Kind(enum.Enum):
    CUMULATIVE = 0
    DELTA = 1
    FINAL_ONLY = 2


class _Params:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.output_kind = kwargs.get("output_kind", _Kind.CUMULATIVE)


class _FakeEngine:
    """Emits `total` ids, 3 per step, from a task separate from the consumer."""

    def __init__(self, total: int):
        self.total = total
        self.aborted = []

    async def generate(self, prompt, params, request_id):
        live: list[int] = []
        ready = asyncio.Queue()

        async def producer():
            nxt = 0
            while nxt < self.total:
                step = list(range(nxt, min(nxt + 3, self.total)))
                live.extend(step)
                nxt += len(step)
                await ready.put(step)
                await asyncio.sleep(0)
            await ready.put(None)

        task = asyncio.create_task(producer())
        try:
            while (step := await ready.get()) is not None:
                ids = step if params.output_kind is _Kind.DELTA else live
                yield types.SimpleNamespace(outputs=[types.SimpleNamespace(token_ids=ids)])
        finally:
            task.cancel()

    async def abort(self, request_id):
        self.aborted.append(request_id)


@pytest.fixture
def fake_vllm(monkeypatch):
    vllm = types.ModuleType("vllm")
    vllm.SamplingParams = _Params
    vllm.TokensPrompt = lambda **kw: kw
    sp = types.ModuleType("vllm.sampling_params")
    sp.RequestOutputKind = _Kind
    monkeypatch.setitem(sys.modules, "vllm", vllm)
    monkeypatch.setitem(sys.modules, "vllm.sampling_params", sp)


def _source(backend, engine):
    cfg = types.SimpleNamespace(min_new_tokens=8)
    layout = types.SimpleNamespace(audio_end_token_id=277394)
    src = backend.VllmTokenSource(cfg, layout)
    src._engine = engine
    return src


async def test_every_token_arrives_once_in_order_while_the_consumer_is_slow(backend, fake_vllm):
    engine = _FakeEngine(total=600)
    got = []
    async for token in _source(backend, engine).stream(
        [2, 277392, 277393], max_new_tokens=600, temperature=0.8, top_k=30
    ):
        got.append(token)
        # What the engine does between tokens: hand a decode to a thread and
        # await it, which lets vLLM's output handler run and extend its list.
        for _ in range(3):
            await asyncio.sleep(0)
    assert got == list(range(600))
    assert len(engine.aborted) == 1


def test_outputs_are_requested_as_deltas(backend, fake_vllm):
    params = _source(backend, _FakeEngine(0)).sampling_params(
        max_new_tokens=10, temperature=0.8, top_k=30
    )
    assert params.output_kind is _Kind.DELTA
    assert params.detokenize is False
