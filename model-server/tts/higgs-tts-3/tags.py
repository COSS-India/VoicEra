"""Higgs TTS 3 control tags: the fixed vocabulary, and how a request reaches it.

The model is steered by tags written into the text itself, `<|category:value|>`.
The vocabulary below is the model's own (PROMPTING.md in bosonai/higgs-tts-3-4b,
and the SGLang-Omni cookbook), copied exactly. Their guidance says anything else
"will degrade the output or be read aloud literally" -- so an unknown tag is a
400 here, never passed through to be spoken.

Two placements, and they are not interchangeable:

* **Delivery** tags (emotion, style, and the prosody speed / pitch / expressive
  values) set how the whole turn is spoken, and must LEAD the input. These come
  from OpenAI's `instructions` field and `speed`.
* **Inline** tags (pauses and sound effects) mark a point in the sentence. They
  can only be written into `input` by the caller, at the place they belong.
  Each `<|sfx:...|>` should be followed by its onomatopoeia
  (`<|sfx:laughter|>Haha`).

`instructions` takes the fixed list only -- free text is refused rather than
guessed at. Accepted spellings, comma- or space-separated, case-insensitive:

    emotion:elation, style:whispering       category:value
    <|emotion:elation|><|style:whispering|> the tag itself
    elation whispering                      the bare value (every value is unique)
    none                                    no delivery tags at all
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

EMOTIONS: tuple[str, ...] = (
    "affection", "amusement", "anger", "arousal", "awe", "bitterness", "confusion",
    "contemplation", "contentment", "determination", "disgust", "elation",
    "enthusiasm", "fear", "helplessness", "longing", "pride", "relief", "sadness",
    "shame", "surprise",
)
STYLES: tuple[str, ...] = ("singing", "shouting", "whispering")
SPEEDS: tuple[str, ...] = ("speed_very_slow", "speed_slow", "speed_fast", "speed_very_fast")
PITCHES: tuple[str, ...] = ("pitch_low", "pitch_high")
EXPRESSIVE: tuple[str, ...] = ("expressive_high", "expressive_low")
PAUSES: tuple[str, ...] = ("pause", "long_pause")
SFX: tuple[str, ...] = (
    "cough", "laughter", "crying", "screaming", "burping", "humming", "sigh", "sniff",
    "sneeze",
)

#: `instructions` meaning "no delivery tags", so a settings dropdown can offer
#: "plain delivery" as a choice rather than as an empty string.
NONE = "none"

#: Approximate rate of each speed tag, from the cookbook. 1.0 is "no tag".
SPEED_FACTORS: dict[str, float] = {
    "speed_very_slow": 0.65,
    "speed_slow": 0.85,
    "speed_fast": 1.2,
    "speed_very_fast": 1.4,
}

#: Delivery slots: one value each per request. The slot name is what a conflict
#: error names, so it is the word a caller would recognise.
_DELIVERY: dict[str, tuple[str, tuple[str, ...]]] = {
    "emotion": ("emotion", EMOTIONS),
    "style": ("style", STYLES),
    "speed": ("prosody", SPEEDS),
    "pitch": ("prosody", PITCHES),
    "expressive": ("prosody", EXPRESSIVE),
}
#: Order the delivery tags are written in. Fixed, so the same instructions
#: always produce the same prompt.
_DELIVERY_ORDER = ("emotion", "style", "speed", "pitch", "expressive")

#: Every tag the model knows, as (category, value) pairs.
KNOWN_TAGS: frozenset[tuple[str, str]] = frozenset(
    [("emotion", v) for v in EMOTIONS]
    + [("style", v) for v in STYLES]
    + [("prosody", v) for v in SPEEDS + PITCHES + EXPRESSIVE + PAUSES]
    + [("sfx", v) for v in SFX]
)

#: Bare value -> delivery slot. Every value is unique across the delivery
#: categories, which is what makes the bare spelling unambiguous.
_SLOT_OF_VALUE: dict[str, str] = {
    value: slot for slot, (_cat, values) in _DELIVERY.items() for value in values
}
assert len(_SLOT_OF_VALUE) == sum(len(v) for _c, v in _DELIVERY.values()), "duplicate tag value"

_TAG = re.compile(r"<\|([^|<>]*)\|>")
_SEPARATORS = re.compile(r"[,;\s]+")


class TagError(ValueError):
    """A request that names a tag the model does not know, or contradicts itself."""

    def __init__(self, message: str, param: str) -> None:
        super().__init__(message)
        self.param = param


@dataclass(frozen=True)
class Delivery:
    """The delivery tags one request asked for, at most one per slot."""

    slots: dict[str, str] = field(default_factory=dict)

    def prefix(self) -> str:
        """The tags as the model expects them: leading, in a fixed order."""
        out = []
        for slot in _DELIVERY_ORDER:
            value = self.slots.get(slot)
            if value:
                category = _DELIVERY[slot][0]
                out.append(f"<|{category}:{value}|>")
        return "".join(out)


def instruction_options() -> list[str]:
    """Every value `instructions` accepts, in `category:value` form, for docs and /v1/voices."""
    return [f"{_DELIVERY[slot][0]}:{v}" for slot in _DELIVERY_ORDER for v in _DELIVERY[slot][1]]


def _token_to_slot(token: str) -> tuple[str, str]:
    """One instruction token -> (slot, value), or TagError."""
    raw = token
    match = _TAG.fullmatch(token)
    if match:
        token = match.group(1)
    token = token.strip().lower()
    if ":" in token:
        category, _, value = token.partition(":")
        category, value = category.strip(), value.strip()
    else:
        category, value = "", token
    slot = _SLOT_OF_VALUE.get(value)
    if slot is None or (category and category != _DELIVERY[slot][0]):
        if (category, value) in KNOWN_TAGS:
            raise TagError(
                f"{raw!r} is an inline tag: it marks a point in the sentence, so write it "
                f"into `input` where it belongs, not into `instructions`",
                "instructions",
            )
        raise TagError(
            f"{raw!r} is not a Higgs delivery tag. `instructions` takes only the fixed "
            f"list: emotion ({', '.join(EMOTIONS)}); style ({', '.join(STYLES)}); "
            f"prosody ({', '.join(SPEEDS + PITCHES + EXPRESSIVE)})",
            "instructions",
        )
    return slot, value


def parse_instructions(instructions: str | None) -> Delivery:
    """`instructions` -> Delivery. Empty or None means no delivery tags at all."""
    slots: dict[str, str] = {}
    if not instructions or not instructions.strip() or instructions.strip().lower() == NONE:
        return Delivery(slots)
    # Tags written back to back (`<|a|><|b|>`) have no separator; give them one.
    text = _TAG.sub(lambda m: f" {m.group(0)} ", instructions)
    for token in _SEPARATORS.split(text):
        if not token:
            continue
        slot, value = _token_to_slot(token)
        previous = slots.get(slot)
        if previous and previous != value:
            raise TagError(
                f"`instructions` asks for two {slot} values ({previous!r} and {value!r}); "
                f"give at most one",
                "instructions",
            )
        slots[slot] = value
    return Delivery(slots)


def speed_tag(speed: float) -> str | None:
    """OpenAI's `speed` -> the nearest of Higgs's four speed tags, or None for normal.

    Higgs has no continuous rate control, so the request is rounded to the
    nearest step (0.65 / 0.85 / 1.0 / 1.2 / 1.4) rather than resampled, which
    would shift the pitch. Anything at or beyond an end gets that end.
    """
    steps = {None: 1.0, **SPEED_FACTORS}
    return min(steps, key=lambda tag: abs(steps[tag] - speed))


def apply_speed(delivery: Delivery, speed: float) -> Delivery:
    """Fold OpenAI's `speed` into the delivery tags.

    A non-default `speed` that disagrees with a speed tag in `instructions` is a
    contradiction and refused; 1.0 is OpenAI's default and means "not asked",
    so it never overrides a tag.
    """
    if speed == 1.0:
        return delivery
    tag = speed_tag(speed)
    current = delivery.slots.get("speed")
    if current and current != tag:
        raise TagError(
            f"`speed` {speed} maps to {tag or 'normal speed'!s}, but `instructions` asks "
            f"for {current}; give one or the other",
            "speed",
        )
    slots = dict(delivery.slots)
    if tag:
        slots["speed"] = tag
    else:
        slots.pop("speed", None)
    return Delivery(slots)


def check_inline_tags(text: str) -> None:
    """Refuse a tag in `input` that the model does not know.

    Delivery tags written by hand at the very start of `input` are accepted too:
    that is exactly where the model wants them, and refusing the model's own
    documented syntax would be perverse.
    """
    for match in _TAG.finditer(text):
        body = match.group(1).strip().lower()
        category, _, value = body.partition(":")
        if (category.strip(), value.strip()) not in KNOWN_TAGS:
            raise TagError(
                f"{match.group(0)!r} in `input` is not a tag Higgs knows; it would be "
                f"read aloud or degrade the audio. Inline tags are prosody "
                f"({', '.join(PAUSES)}) and sfx ({', '.join(SFX)})",
                "input",
            )


def compose_input(text: str, delivery: Delivery) -> str:
    """The text the model is given: delivery tags first, then the caller's text."""
    return delivery.prefix() + text
