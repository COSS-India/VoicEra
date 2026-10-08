"""tts/rumik-oss-1/streaming.py against a one-shot MimiModel.decode.

The streaming decoder re-implements Mimi's decoder transformer step so that
streams at different positions can share one batched call, and carries each
stream's upsample, KV and SEANet history between chunks. If any of that is off
it does not error: the audio is merely wrong. So the contract is checked
directly -- every stream's streamed audio must equal a one-shot decode of its
whole utterance -- on a model whose decoder transformer is strong enough to
matter (a freshly initialised one barely contributes, and would pass anything),
with the cases that break naive implementations:

  * streams of different lengths, joining at different times, in one step
  * an utterance longer than the 250-step attention window (the ring wraps)
  * a slot reused by a new stream
  * a final chunk shorter than the rest

Needs real torch and transformers; the suite's torch stub skips it.
"""
import importlib.util
import random
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
if not hasattr(torch, "tensor"):
    pytest.skip("tests/stubs/torch.py stands in for torch here; needs the real one",
                allow_module_level=True)
transformers = pytest.importorskip("transformers")

MODEL = Path(__file__).resolve().parent.parent / "tts" / "rumik-oss-1"
_spec = importlib.util.spec_from_file_location("rumik_streaming", MODEL / "streaming.py")
streaming = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = streaming
_spec.loader.exec_module(streaming)

Q = 8


@pytest.fixture(scope="module")
def mimi():
    torch.manual_seed(0)
    model = transformers.MimiModel(transformers.MimiConfig(num_quantizers=Q)).eval()
    with torch.no_grad():
        for p in model.decoder_transformer.parameters():
            p.normal_(0, 0.05 if p.dim() > 1 else 0.5)
    return model


def whole(mimi, codes):
    with torch.inference_mode():
        audio = mimi.decode(torch.tensor(codes).T[None]).audio_values[0, 0]
    return (audio.float().clamp(-1, 1) * 32767.0).to(torch.int16).numpy().astype(int)


def stream(mimi, utterances, starts, chunk=2, slots=None, slot_of=None):
    """Run utterances through one streamer, each joining at its start tick."""
    import numpy as np

    st = streaming.MimiStreamer(mimi, slots=slots or len(utterances))
    slot_of = slot_of or list(range(len(utterances)))
    out = [[] for _ in utterances]
    cursor = [0] * len(utterances)
    tick = 0
    while any(c < len(u) for c, u in zip(cursor, utterances, strict=True)):
        batch, who = [], []
        for i, u in enumerate(utterances):
            busy = {c.slot for c in batch}
            if tick >= starts[i] and cursor[i] < len(u) and slot_of[i] not in busy:
                part = u[cursor[i]:cursor[i] + chunk]
                batch.append(streaming.Chunk(slot_of[i], part, start=cursor[i] == 0))
                who.append(i)
                cursor[i] += len(part)
        for i, pcm in zip(who, st.step(batch), strict=True):
            out[i].append(pcm)
        tick += 1
    return [np.frombuffer(b"".join(o), "<i2").astype(int) for o in out]


def frames(n, seed):
    rng = random.Random(seed)
    return [[rng.randrange(2048) for _ in range(Q)] for _ in range(n)]


def test_concurrent_streams_of_different_lengths_match_a_whole_decode(mimi):
    utterances = [frames(n, s) for s, n in enumerate([3, 17, 40, 61])]
    got = stream(mimi, utterances, starts=[0, 2, 5, 1])
    for u, g in zip(utterances, got, strict=True):
        ref = whole(mimi, u)
        assert len(g) == len(ref)
        assert abs(g - ref).max() <= 2              # int16 steps: float noise


def test_an_utterance_longer_than_the_attention_window(mimi):
    u = frames(180, 7)                               # 360 steps > the 250-step window
    (got,) = stream(mimi, [u], starts=[0])
    assert abs(got - whole(mimi, u)).max() <= 2


def test_a_reused_slot_starts_clean(mimi):
    a, b = frames(20, 1), frames(15, 2)
    # Both use slot 0: b joins after a has finished (a takes 10 ticks).
    got = stream(mimi, [a, b], starts=[0, 12], slots=1, slot_of=[0, 0])
    assert abs(got[1] - whole(mimi, b)).max() <= 2


def test_odd_chunk_sizes_and_a_short_final_chunk(mimi):
    u = frames(23, 3)
    (got,) = stream(mimi, [u], starts=[0], chunk=3)
    assert abs(got - whole(mimi, u)).max() <= 2


def test_less_seanet_history_than_measured_is_wrong(mimi):
    """Guards the measured constant: below it the output must not pass."""
    import numpy as np

    u = frames(30, 4)
    st = streaming.MimiStreamer(mimi, slots=1, seanet_context=streaming.SEANET_CONTEXT_STEPS - 2)
    out = [st.step([streaming.Chunk(0, u[i:i + 2], start=i == 0)])[0] for i in range(0, 30, 2)]
    got = np.frombuffer(b"".join(out), "<i2").astype(int)
    assert abs(got - whole(mimi, u)).max() > 100
