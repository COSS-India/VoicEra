"""Prompt construction, as explicit token ids.

Two reasons this emits token *ids* rather than a string:

  * The tokenizer auto-prepends BOS. Building the prompt as text and letting it
    tokenise gives you two BOS tokens and noticeably worse audio.
  * The Indic template's speaker/style markers are asymmetric special tokens
    (``<|speaker>`` opens, ``<speaker|>`` closes). Round-tripping them through
    text is fragile; addressing them by id is not.

Control-token ids are identical between upstream English Orpheus and the
AI4Bharat Indic fine-tune, so both templates live here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Turn structure
TOK_SOH = 128259            # start of human turn
TOK_BOS = 128000            # begin_of_text
TOK_EOT = 128009            # end of turn
TOK_EOH = 128260            # end of human turn
TOK_SOA = 128261            # start of AI turn
TOK_SOS = 128257            # start of speech
TOK_EOS = 128258            # end of speech -- the speech-specific stop token
TOK_TEXT_EOS = 128001       # the Llama backbone's own eos, per config.json

# Resolved by NAME against the checkpoint's tokenizer, the way the checkpoint's
# own inference.py does it (`convert_tokens_to_ids("<|end_of_speech|>")`). The
# ids above are a fallback for a tokenizer that does not carry the name; they
# are not the source of truth. See token_contract.md in the checkpoint, which
# states plainly: "A token ID is meaningless without this contract."
NAME_END_OF_SPEECH = "<|end_of_speech|>"

# Indic template markers (asymmetric; verified against the checkpoint tokenizer)
TOK_SPEAKER_OPEN = 156938   # <|speaker>
TOK_SPEAKER_CLOSE = 156939  # <speaker|>
TOK_STYLE_OPEN = 156940     # <|style>
TOK_STYLE_CLOSE = 156941    # <style|>


@dataclass(frozen=True)
class StopTokens:
    """How one generation may end, read off the checkpoint rather than assumed.

    ``hard`` closes the audio span. Per the checkpoint's token_contract.md,
    ``<|end_of_speech|>`` is the *only* token that means "the speech is over",
    so it is the one safe unconditional stop.

    ``soft`` is the backbone's own text eos. The checkpoint's inference.py hands
    it to ``generate`` as **both** ``eos_token_id`` and ``pad_token_id``, so its
    appearance is ambiguous by construction: it can close a turn, or it can be
    padding. Obeying it unconditionally truncates an utterance at the first
    sentence boundary in styles trained on short single-sentence items; ignoring
    it entirely lets a missed ``<|end_of_speech|>`` run on to ``max_tokens`` as
    babble. So it is judged against the text rather than obeyed -- see
    ``TTSEngine._text_eos_is_final``.
    """

    hard: tuple[int, ...]
    soft: tuple[int, ...]

    @property
    def all(self) -> tuple[int, ...]:
        return self.hard + self.soft


def resolve_stop_tokens(tokenizer) -> StopTokens:
    """Ask the tokenizer which ids end a generation, by name.

    Falls back to the documented ids only when the tokenizer cannot resolve a
    name, and never returns an empty ``hard`` set -- a generation with no
    terminator would run to ``max_tokens`` every time.
    """
    hard: list[int] = []
    soft: list[int] = []

    end_of_speech = None
    if tokenizer is not None:
        try:
            end_of_speech = tokenizer.convert_tokens_to_ids(NAME_END_OF_SPEECH)
        except Exception:                                        # noqa: BLE001
            end_of_speech = None
        # An unknown name resolves to the unk id or None depending on the
        # tokenizer; neither is a stop token.
        if end_of_speech is None or end_of_speech == getattr(
            tokenizer, "unk_token_id", object()
        ):
            end_of_speech = None
    hard.append(TOK_EOS if end_of_speech is None else int(end_of_speech))

    text_eos = getattr(tokenizer, "eos_token_id", None) if tokenizer else None
    text_eos = TOK_TEXT_EOS if text_eos is None else int(text_eos)
    # If the checkpoint ever makes its text eos the same token as end-of-speech,
    # there is nothing ambiguous left to judge.
    if text_eos not in hard:
        soft.append(text_eos)

    return StopTokens(hard=tuple(hard), soft=tuple(soft))

TEMPLATE_INDIC = "indic"
TEMPLATE_PLAIN = "plain"
TEMPLATES = (TEMPLATE_INDIC, TEMPLATE_PLAIN)


def build_prompt_token_ids(
    tokenizer,
    template: str,
    text: str,
    voice: str,
    style: Optional[str] = None,
) -> list[int]:
    """Build the prompt for one utterance.

    ``template`` is ``"indic"`` (speaker + style markers, the AI4Bharat
    checkpoint) or ``"plain"`` (``"{voice}: {text}"``, upstream English Orpheus).
    """

    def encode(s: str) -> list[int]:
        # add_special_tokens=False is what prevents the double-BOS above.
        return tokenizer.encode(s, add_special_tokens=False)

    if template == TEMPLATE_INDIC:
        # A style of None means the caller asked for none, so the block is left
        # out entirely rather than filled with a guess. It used to fall back to
        # "CONV", which belongs to the previous checkpoint's style set -- the
        # current one was never trained on that string and would be conditioned
        # on a token sequence that means nothing to it.
        style_block: list[int] = []
        if style:
            style_block = [TOK_STYLE_OPEN] + encode(style) + [TOK_STYLE_CLOSE] + encode("\n")
        return (
            [TOK_SOH, TOK_BOS, TOK_SPEAKER_OPEN]
            + encode(voice)
            + [TOK_SPEAKER_CLOSE]
            + encode("\n")
            + style_block
            + encode(text)
            + [TOK_EOT, TOK_EOH, TOK_SOA, TOK_SOS]
        )
    if template == TEMPLATE_PLAIN:
        return (
            [TOK_SOH, TOK_BOS]
            + encode(f"{voice}: {text}")
            + [TOK_EOT, TOK_EOH, TOK_SOA, TOK_SOS]
        )
    raise ValueError(f"unknown prompt template {template!r}; expected one of {TEMPLATES}")
