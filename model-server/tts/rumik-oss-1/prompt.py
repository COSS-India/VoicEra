"""Composing the one string rumik-oss-1 is conditioned on.

The model reads a single flat prompt:

    <text>Ira: <description="happy, Hindi accent, steady pace"> नमस्ते<audio>

Three separate things are folded into it -- the speaker, the delivery
description and the text -- and the OpenAI speech schema keeps them apart as
`voice`, `instructions` and `input`. Recomposition therefore happens here, on
the server, exactly as tts/indic-parler does it. `tests/test_tts_request_parity.py`
exists because that recomposition drifting changes the voice while every other
test still passes, so keep the assembly in one function rather than inline at
the call site.

The delivery description is the model's own vocabulary, not free prose that
happens to work: emotion, accent and pace, comma-separated, as the model card's
examples show ("happy, Telugu accent, fast pace"). Anything is accepted -- the
model was trained on natural-language descriptions -- but a caller sending a
sentence should not expect the control an example-shaped string gives.
"""
from __future__ import annotations

#: The model's own control markers. A caller must not be able to write these
#: into the prompt: `<audio>` is what ends the text span and begins generation,
#: so an `input` containing it would make the model start speaking mid-sentence
#: and ignore everything after. That is not a crash -- it is a truncated
#: utterance with no error anywhere, so it is refused rather than escaped.
CONTROL_MARKERS = ("<text>", "<audio>", "<description=")

#: Inline vocalisations the model understands inside `input`. Listed so the
#: refusal above can say what IS allowed; they are passed through untouched.
VOCALISATIONS = ("<laugh>", "<chuckle>", "<sigh>")


class PromptError(ValueError):
    """The request cannot be turned into a prompt. Always a 400, never a 500."""


def check_text(text: str, max_chars: int) -> str:
    text = text.strip()
    if not text:
        raise PromptError("input is empty")
    if len(text) > max_chars:
        raise PromptError(f"input is {len(text)} characters; the limit is {max_chars}")
    for marker in CONTROL_MARKERS:
        if marker in text:
            raise PromptError(
                f"input may not contain {marker!r}: it is one of the model's own control "
                f"markers and would truncate the utterance. Inline vocalisations "
                f"({', '.join(VOCALISATIONS)}) are fine; delivery goes in `instructions`."
            )
    return text


def build_prompt(*, voice: str, instructions: str | None, text: str) -> str:
    """The exact string the model is conditioned on.

    `instructions` is omitted entirely when empty rather than emitted as an
    empty description. `<description="">` is a real token sequence the model
    would condition on, and conditioning on "no description" is not the same
    thing as not conditioning at all.
    """
    style = instructions.strip() if instructions else ""
    described = f'<description="{style}"> ' if style else ""
    return f"<text>{voice}: {described}{text}<audio>"
