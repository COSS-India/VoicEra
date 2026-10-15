"""bench/stt_ab.py decides whether a checkpoint ships, so its arithmetic is pinned.

The scoring is deliberately simple; what matters is that it is the same for both
servers and that it is right -- a WER computed over the wrong token boundaries
would make a regression look like an improvement.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "bench"))

from stt_ab import edits, normalise  # noqa: E402


def test_edits_is_levenshtein():
    assert edits([], []) == 0
    assert edits(list("abc"), list("abc")) == 0
    assert edits(list("abc"), []) == 3                    # deletions
    assert edits([], list("abc")) == 3                    # insertions
    assert edits(list("kitten"), list("sitting")) == 3
    assert edits(["a", "b", "c"], ["a", "x", "c"]) == 1   # one substitution


def test_normalise_drops_the_danda_and_punctuation():
    """Devanagari full stop is a P* character like any other; leaving it in
    would count every sentence end as a word error on one side only."""
    assert normalise("राम  घर गया।") == "राम घर गया"
    assert normalise("Hello, World!") == "hello world"


def test_normalise_composes_unicode_before_comparing():
    """The same Devanagari text can arrive composed or decomposed; scoring must
    not see a difference that a reader would not."""
    composed = "क़"                 # क़ as one code point
    decomposed = "क़"         # क + nukta
    assert normalise(composed) == normalise(decomposed)
