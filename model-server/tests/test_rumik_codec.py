"""The rumik unit-token arithmetic, which decides speech from noise.

`tts/rumik-oss-1/codec.py` is a transcription. The first build of that folder
called the checkpoint's own `audio_tokens_to_codes` precisely so this rule would
not be transcribed; the vLLM engine gives that up, because serving through vLLM
means loading the checkpoint as the plain `Cohere2ForCausalLM` it subclasses and
dropping `trust_remote_code` along with its coupling to a pinned `transformers`.

A slip here does not raise. It shifts every frame by one quantizer and produces
a stream of plausible bytes that sound like noise down a phone line -- the same
failure mode `test_tts_format_negotiation.py` exists for, one layer down. So
every branch of the rule gets a case, including the three ways a frame can be
abandoned.

The layout cases are built with `unit_token`, the inverse of the `divmod` under
test, so a case says what it means (`code 5 at quantizer 3`) rather than a bare
integer nobody can check by eye.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "tts" / "rumik-oss-1"

# Loaded by path rather than import: the model folder is a build context, not a
# package, and `codec` is too generic a name to put on sys.path beside the other
# model folders. Registered in sys.modules BEFORE exec_module, because
# `codec.py` uses `from __future__ import annotations` and @dataclass resolves
# its field types through sys.modules[cls.__module__] -- absent, that lookup
# returns None and the decorator dies on import.
_spec = importlib.util.spec_from_file_location("rumik_codec", MODEL / "codec.py")
codec = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = codec
_spec.loader.exec_module(codec)

# Where fetch.sh puts the weights -- models/<RUMIK_MODEL_DIRNAME>/, not the
# folder root. Pointing this at MODEL/config.json made the check below skip
# unconditionally, on the server as well as here, which is a test that can never
# run rather than one that is merely inactive.
CHECKPOINT = MODEL / "models" / "rumik-oss-1"

needs_checkpoint_config = pytest.mark.skipif(
    not (CHECKPOINT / "config.json").is_file(),
    reason="weights are fetched, not committed; run tts/rumik-oss-1/fetch.sh first",
)

# The layout the committed folder is written against. Kept as literals rather
# than read from the checkpoint, so a checkpoint whose vocabulary moved fails
# loudly here instead of silently re-tuning every other test in this file.
LAYOUT = codec.CodecLayout(
    first_unit_id=261008,
    last_unit_id=277391,
    num_quantizers=8,
    codebook_size=2048,
    audio_end_token_id=277394,
    frame_rate_hz=12.5,
    speakers=("Ira", "Aisha", "Siya", "Zoya"),
)


def frame(*codes: int) -> list[int]:
    """The token ids carrying one complete frame of `codes`, in round-robin order."""
    return [codec.unit_token(c, q, LAYOUT) for q, c in enumerate(codes)]


EIGHT = (1, 2, 3, 4, 5, 6, 7, 8)
NINE = (9, 10, 11, 12, 13, 14, 15, 16)


# ----------------------------------------------------------------- the layout

def test_last_unit_id_matches_the_declared_one():
    assert LAYOUT.first_unit_id + LAYOUT.codebook_size * LAYOUT.num_quantizers - 1 == 277391


def test_one_second_of_speech_costs_a_hundred_tokens():
    # 8 quantizers x 12.5 Hz. The number every realtime claim is measured against.
    assert LAYOUT.tokens_per_second == 100.0
    assert LAYOUT.samples_per_frame_at == pytest.approx(0.08)


def test_allowed_ids_are_the_units_plus_the_end_token():
    allowed = LAYOUT.allowed_token_ids()
    assert len(allowed) == LAYOUT.codebook_size * LAYOUT.num_quantizers + 1
    assert allowed[0] == LAYOUT.first_unit_id
    assert allowed[-2] == LAYOUT.last_unit_id
    # Without it the model cannot stop; the engine would run every request to
    # max_tokens and the stop head is not available under vLLM.
    assert allowed[-1] == LAYOUT.audio_end_token_id
    assert len(set(allowed)) == len(allowed)


def test_unit_token_is_the_inverse_of_the_divmod():
    for code, quantizer in ((0, 0), (1, 7), (2047, 7), (2047, 0), (1023, 4)):
        tid = codec.unit_token(code, quantizer, LAYOUT)
        assert LAYOUT.first_unit_id <= tid <= LAYOUT.last_unit_id
        assert divmod(tid - LAYOUT.first_unit_id, LAYOUT.num_quantizers) == (code, quantizer)


@pytest.mark.parametrize(("code", "quantizer"), [(-1, 0), (2048, 0), (0, -1), (0, 8)])
def test_unit_token_refuses_what_cannot_be_encoded(code, quantizer):
    with pytest.raises(ValueError):
        codec.unit_token(code, quantizer, LAYOUT)


# ------------------------------------------------------------ frame assembly

def test_nothing_in_nothing_out():
    assert codec.frames_from_tokens([], LAYOUT) == []


def test_a_clean_frame_round_trips():
    assert codec.frames_from_tokens(frame(*EIGHT), LAYOUT) == [list(EIGHT)]


def test_two_clean_frames():
    assert codec.frames_from_tokens(frame(*EIGHT) + frame(*NINE), LAYOUT) == [
        list(EIGHT), list(NINE)
    ]


def test_an_incomplete_trailing_frame_is_not_returned():
    # Seven of eight quantizers cannot be decoded, and half a frame of audio is
    # worse than none -- this is the `DROPPED 1` seen on hardware.
    assert codec.frames_from_tokens(frame(*EIGHT) + frame(*NINE)[:7], LAYOUT) == [list(EIGHT)]


def test_the_end_token_ends_it():
    tokens = frame(*EIGHT) + [LAYOUT.audio_end_token_id] + frame(*NINE)
    assert codec.frames_from_tokens(tokens, LAYOUT) == [list(EIGHT)]


# --------------------------------------------- the three ways a frame is lost

def test_a_stray_token_drops_the_partial_frame_and_assembly_resumes():
    """A non-unit id mid-frame costs that frame, not the rest of the clip."""
    tokens = frame(*EIGHT)[:3] + [42] + frame(*NINE)
    assert codec.frames_from_tokens(tokens, LAYOUT) == [list(NINE)]


def test_after_a_stray_assembly_waits_for_a_quantizer_zero():
    """Resync is to a frame boundary, not to the next unit token."""
    tokens = [42] + frame(*EIGHT)[4:] + frame(*NINE)
    assert codec.frames_from_tokens(tokens, LAYOUT) == [list(NINE)]


def test_an_out_of_order_quantizer_zero_starts_the_next_frame():
    """The one case that is not simply discarded.

    A token off the round robin abandons the partial frame -- but a
    quantizer-0 token is itself the start of a frame, so it is kept. Dropping
    it too would cost a second frame for one bad token, which is the difference
    upstream's `frame = [code] if q == 0 else []` encodes.
    """
    tokens = frame(*EIGHT)[:3] + frame(*NINE)
    assert codec.frames_from_tokens(tokens, LAYOUT) == [list(NINE)]


def test_an_out_of_order_non_zero_quantizer_is_discarded():
    tokens = frame(*EIGHT)[:3] + [codec.unit_token(99, 6, LAYOUT)] + frame(*NINE)
    assert codec.frames_from_tokens(tokens, LAYOUT) == [list(NINE)]


def test_code_zero_is_a_valid_code():
    """0 is a real codec code, not a sentinel. Dropping it would silence frames."""
    zeros = (0,) * LAYOUT.num_quantizers
    assert codec.frames_from_tokens(frame(*zeros), LAYOUT) == [list(zeros)]


# ------------------------------------------------------------- the real thing

@needs_checkpoint_config
def test_the_fetched_checkpoint_matches_the_layout_this_folder_assumes():
    fetched = codec.CodecLayout.from_config(CHECKPOINT)
    assert fetched == LAYOUT, (
        "the fetched checkpoint's audio vocabulary differs from what this folder "
        "was written against; every frame would shift"
    )


def test_codes_tensor_has_the_shape_mimi_decode_wants():
    torch = pytest.importorskip("torch")
    tensor = codec.codes_tensor([list(EIGHT), list(NINE)])
    assert tensor.shape == (1, LAYOUT.num_quantizers, 2)
    assert tensor.dtype == torch.long
    # [1, Q, T]: quantizer-major, frame-minor -- the transpose is the whole point.
    assert tensor[0, :, 0].tolist() == list(EIGHT)
    assert tensor[0, 0, :].tolist() == [EIGHT[0], NINE[0]]
