"""The orpheus audio-token arithmetic, which decides speech from noise.

`tts/orpheus/src/orpheus_server/codec.py` maps a generated token id to a SNAC
code from the token's position in the stream. The rule is one subtraction, and
getting it wrong does not raise: it shifts the frame phase and produces a stream
of plausible bytes that sound like babble down a phone line. Nothing between
here and the speaker can tell that from speech, so the rule is pinned here.

The case this file was written for is the UPPER bound. The audio block ends at
AUDIO_BASE + 7*4096 - 1 = 156937 and the Indic template's speaker and style
markers begin at 156938, immediately above it. A lower-bound-only check accepts
those four ids as codes 28672..28675 at every frame phase -- out of range, but
non-negative -- so `StreamingAudioBuffer` counts them, every later token is read
at the wrong phase, and the poisoned code invalidates each decode window it
appears in. A marker is what the model reaches for when it closes a turn, so the
damage lands on the closing syllables of an utterance.

The layout is kept as literals rather than imported from the module under test,
so a checkpoint whose vocabulary moved fails loudly here instead of silently
re-tuning every case in this file.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "tts" / "orpheus" / "src" / "orpheus_server" / "codec.py"

# Loaded by path: the model folder is a build context, not a package, and
# `codec` is too generic a name to put on
# sys.path beside the other model folders. Registered in sys.modules before
# exec_module because the module uses `from __future__ import annotations`.
_spec = importlib.util.spec_from_file_location("orpheus_codec", MODULE)
codec = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = codec
_spec.loader.exec_module(codec)

# The layout the committed folder is written against.
AUDIO_BASE = 128266
CODES_PER_FRAME = 7
CODEBOOK_SIZE = 4096
FIRST_ID_ABOVE_BLOCK = AUDIO_BASE + CODES_PER_FRAME * CODEBOOK_SIZE  # 156938

# Control tokens from prompt.py. Everything here is BELOW the audio block, which
# is why a lower-bound check was enough to reject them and why the gap above the
# block went unnoticed.
CONTROL_BELOW = {
    "SOH": 128259, "BOS": 128000, "EOT": 128009,
    "EOH": 128260, "SOA": 128261, "SOS": 128257, "EOS": 128258,
}
# The Indic template's markers -- the ids that sit above the block.
MARKERS = {
    "SPEAKER_OPEN": 156938, "SPEAKER_CLOSE": 156939,
    "STYLE_OPEN": 156940, "STYLE_CLOSE": 156941,
}

PHASES = range(CODES_PER_FRAME)


def audio_token(code: int, phase: int) -> int:
    """The token id carrying `code` at frame-phase `phase` -- inverse of the rule."""
    return AUDIO_BASE + phase * CODEBOOK_SIZE + code


def frame(*codes: int) -> list[int]:
    """The seven token ids carrying one complete frame."""
    assert len(codes) == CODES_PER_FRAME
    return [audio_token(c, p) for p, c in enumerate(codes)]


# -- the mapping rule --------------------------------------------------------
def test_layout_matches_the_module():
    assert codec.AUDIO_BASE == AUDIO_BASE
    assert codec.CODES_PER_FRAME == CODES_PER_FRAME
    assert codec.CODEBOOK_SIZE == CODEBOOK_SIZE


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("code", [0, 1, 2047, 4094, 4095])
def test_audio_ids_round_trip_at_every_phase(code, phase):
    """Code 0 is audio, and so is 4095. Both edges are real."""
    assert codec.token_id_to_code(audio_token(code, phase), phase) == code


@pytest.mark.parametrize("name,token_id", sorted(CONTROL_BELOW.items()))
@pytest.mark.parametrize("phase", PHASES)
def test_control_tokens_below_the_block_are_rejected(name, token_id, phase):
    assert codec.token_id_to_code(token_id, phase) is None


@pytest.mark.parametrize("name,token_id", sorted(MARKERS.items()))
@pytest.mark.parametrize("phase", PHASES)
def test_indic_markers_are_rejected_at_every_phase(name, token_id, phase):
    """The regression. Each of these was accepted as code 28672..28675."""
    assert codec.token_id_to_code(token_id, phase) is None


@pytest.mark.parametrize("phase", PHASES)
def test_the_block_boundary_is_exact(phase):
    """One id below the boundary is audio; the boundary itself is not."""
    assert codec.token_id_to_code(FIRST_ID_ABOVE_BLOCK - 1, CODES_PER_FRAME - 1) == CODEBOOK_SIZE - 1
    assert codec.token_id_to_code(FIRST_ID_ABOVE_BLOCK, phase) is None


# -- the property that actually protects the audio ---------------------------
def collect(tokens):
    """Push `tokens` through a fresh buffer; return (windows, codes, count)."""
    buffer = codec.StreamingAudioBuffer()
    windows = []
    for token_id in tokens:
        pending = buffer.push_token(token_id)
        if pending is not None:
            windows.append((list(pending[0]), pending[1]))
    tail = buffer.flush()
    if tail is not None:
        windows.append((list(tail[0]), tail[1]))
    return windows, list(buffer.codes), buffer.count


SIX_FRAMES = [frame(*[(f * 7 + i) % CODEBOOK_SIZE for i in range(7)]) for f in range(6)]
CLEAN = [t for f in SIX_FRAMES for t in f]


@pytest.mark.parametrize("name,marker", sorted(MARKERS.items()))
@pytest.mark.parametrize("at", [0, 7, 10, 21, len(CLEAN)])
def test_a_marker_anywhere_leaves_the_audio_untouched(name, marker, at):
    """A rejected token must not advance the phase or enter the code list.

    This is the whole point: `push_token` returning None is not enough, it must
    also leave `count` alone, or every subsequent token is read one codebook out.
    """
    polluted = CLEAN[:at] + [marker] + CLEAN[at:]
    assert collect(polluted) == collect(CLEAN)


def test_no_window_carries_an_out_of_range_code():
    """Out-of-range codes reach the SNAC decoder as a CUDA assert, so none may."""
    for window, _ in collect(CLEAN)[0]:
        assert all(0 <= c < CODEBOOK_SIZE for c in window)


# -- the emit tiling ---------------------------------------------------------
def test_emit_slices_tile_the_stream_exactly_once():
    """head [f0 f1], then one middle frame each, then tail [fN-2 fN-1]."""
    windows, _, _ = collect(CLEAN)
    samples = codec.SAMPLES_PER_FRAME
    emitted = sum((e.stop - e.start) // samples for _, e in windows)
    assert emitted == len(SIX_FRAMES)
    assert windows[0][1] == codec.EMIT_HEAD
    assert windows[-1][1] == codec.EMIT_TAIL
    assert all(e == codec.EMIT_MIDDLE for _, e in windows[1:-1])


def test_a_stream_shorter_than_one_window_emits_nothing():
    """Fewer than four frames never fills a window; flush must not invent one."""
    windows, _, _ = collect([t for f in SIX_FRAMES[:3] for t in f])
    assert windows == []
