"""The parts of tts/rumik-oss-1/vllm_backend.py that need no GPU to be wrong.

`check_memory_budget` exists because RUMIK_GPU_MEMORY_UTILIZATION is a fraction
of the card's TOTAL memory and its default, 0.12, was sized for a 143 GB H200.
Carried to a 24 GB card it reserves less than the weights, and vLLM then fails
deep in its profiler about KV cache blocks. The check turns that into a message
naming the knob and a value that would work -- and must never refuse the
configuration that is known to run.
"""
import importlib.util
import sys
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
