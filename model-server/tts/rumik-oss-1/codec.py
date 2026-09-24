"""The unit-token layout, and generated ids -> Mimi codec frames.

This arithmetic used to be borrowed: the first build called the checkpoint's own
``RumikOSSForCausalLM.audio_tokens_to_codes``, deliberately, so that the rule
deciding whether output is speech or noise lived in one place and that place was
upstream's.

The vLLM engine gives it up on purpose. Serving through vLLM loads the
checkpoint through vLLM's own Cohere2 implementation (see rumik_vllm_plugin.py),
and never imports ``modeling_rumik_oss.py`` -- ``trust_remote_code`` is still
needed, but only so transformers will read the config class. That removes the
coupling to upstream's modeling code under whichever `transformers` vLLM happens
to pin. The cost is this file. It is twenty
lines of ``divmod``, and ``tests/test_rumik_codec.py`` pins every branch of it
against the cases upstream's own implementation defines, so a transcription slip
fails a test rather than producing plausible noise.

Layout, from the checkpoint's configuration_rumik_oss.py, quoted:

    The unit tokens are laid out code-major, quantizer-minor::

        <0_0> <0_1> ... <0_7> <1_0> ... <2047_7>

    so for any id in ``[first_unit_id, last_unit_id]``::

        code      = (token_id - first_unit_id) // num_quantizers
        quantizer = (token_id - first_unit_id) %  num_quantizers

One difference from upstream, and it is intentional. Theirs raises when no
complete frame is found, which is right for a one-shot call over a finished
generation. Ours returns an empty list: it is called incrementally on a growing
token list, where "no complete frame yet" is the normal state for the first
eight tokens of every request, not an error.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CodecLayout:
    """Where the audio vocabulary lives, read from the checkpoint's config.json.

    Read as plain JSON rather than through a config class: the vLLM path does
    not import the checkpoint's remote code, and these five numbers are the
    whole of what it would have given us.
    """

    first_unit_id: int
    last_unit_id: int
    num_quantizers: int
    codebook_size: int
    audio_end_token_id: int
    frame_rate_hz: float
    speakers: tuple[str, ...]
    #: The prompt's framing ids. Optional so a layout can be written by hand in
    #: a test; from_config always fills them, and check_prompt_ids uses them.
    bos_token_id: int | None = None
    text_start_token_id: int | None = None
    audio_start_token_id: int | None = None

    @classmethod
    def from_config(cls, model_path: str | Path) -> CodecLayout:
        raw = json.loads((Path(model_path) / "config.json").read_text(encoding="utf-8"))
        missing = [k for k in ("first_unit_id", "num_quantizers", "codebook_size",
                               "audio_end_token_id") if raw.get(k) is None]
        if missing:
            raise ValueError(
                f"config.json is missing {missing}, so the audio vocabulary cannot be "
                f"located. This checkpoint is not a rumik-oss layout."
            )
        first = int(raw["first_unit_id"])
        quantizers = int(raw["num_quantizers"])
        codebook = int(raw["codebook_size"])
        # Derivable, and derived rather than trusted: a hand-edited config that
        # disagrees with itself would otherwise shift every frame silently.
        last = first + codebook * quantizers - 1
        declared = raw.get("last_unit_id")
        if declared is not None and int(declared) != last:
            raise ValueError(
                f"config.json says last_unit_id={declared} but first_unit_id + "
                f"codebook_size * num_quantizers - 1 = {last}. One of them is wrong, "
                f"and guessing which would shift every frame."
            )
        return cls(
            first_unit_id=first,
            last_unit_id=last,
            num_quantizers=quantizers,
            codebook_size=codebook,
            audio_end_token_id=int(raw["audio_end_token_id"]),
            frame_rate_hz=float(raw.get("frame_rate_hz", 12.5)),
            speakers=tuple(raw.get("speakers") or ()),
            bos_token_id=_optional_int(raw.get("bos_token_id")),
            text_start_token_id=_optional_int(raw.get("text_start_token_id")),
            audio_start_token_id=_optional_int(raw.get("audio_start_token_id")),
        )

    @property
    def samples_per_frame_at(self) -> float:
        """Audio seconds one frame carries. 12.5 Hz -> 80 ms."""
        return 1.0 / self.frame_rate_hz

    @property
    def tokens_per_second(self) -> float:
        """Tokens one second of speech costs. 8 x 12.5 = 100."""
        return self.frame_rate_hz * self.num_quantizers

    def allowed_token_ids(self) -> list[int]:
        """Every id the model may legally emit inside an <audio> span.

        The unit range plus ``</audio>`` -- exactly what the checkpoint's
        ``audio_token_ids()`` returns. NOT passed to vLLM's
        ``SamplingParams.allowed_token_ids``, which is capped at 1024 entries;
        the vLLM path applies the same set as a mask in the model's
        ``compute_logits`` (rumik_vllm_plugin.py). Kept as the reference that
        mask is checked against. Leaving the end token out would make the model
        unable to stop; leaving anything else in would let it emit text ids
        mid-frame.
        """
        return [*range(self.first_unit_id, self.last_unit_id + 1), self.audio_end_token_id]


def _optional_int(value) -> int | None:
    return None if value is None else int(value)


def check_prompt_ids(ids, layout: CodecLayout) -> None:
    """Refuse a tokenizer that does not frame the prompt the way the model was trained.

    The model card: ``[BOS] <text>{SPEAKER}: ... {TEXT}<audio>`` -- "the
    tokenizer adds [BOS] itself". Two ways that silently goes wrong, neither of
    which errors anywhere downstream:

      * no BOS, because a tokenizer or transformers upgrade changed the default
        for ``add_special_tokens`` -- the model then conditions on a sequence
        it never saw, and the voice degrades rather than breaks;
      * ``<text>`` or ``<audio>`` split into ordinary sub-word pieces, because
        they were not loaded as added tokens -- the model never sees the cue to
        start speaking.

    So the ids of one real prompt are checked once, at startup, against the ids
    config.json declares. Ids the layout does not know are not checked.
    """
    ids = [int(i) for i in ids]
    if not ids:
        raise ValueError("the tokenizer produced no ids for the prompt")
    problems = []
    if layout.bos_token_id is not None and ids[0] != layout.bos_token_id:
        problems.append(f"it does not start with BOS {layout.bos_token_id} (got {ids[0]})")
    start = 1 if layout.bos_token_id is not None else 0
    if (layout.text_start_token_id is not None
            and (len(ids) <= start or ids[start] != layout.text_start_token_id)):
        problems.append(f"<text> is not the single id {layout.text_start_token_id} after BOS")
    if layout.audio_start_token_id is not None and ids[-1] != layout.audio_start_token_id:
        problems.append(
            f"it does not end with the single <audio> id {layout.audio_start_token_id} "
            f"(got {ids[-1]})"
        )
    if problems:
        raise ValueError(
            "the tokenizer frames the prompt differently from the model card's "
            "[BOS] <text>...<audio>: " + "; ".join(problems)
        )


def frames_from_tokens(token_ids, layout: CodecLayout) -> list[list[int]]:
    """Generated ids -> complete codec frames, as ``[[c0..c7], ...]``.

    Transcribed from the checkpoint's ``audio_tokens_to_codes``, including its
    resynchronisation rule, which is the part worth stating in words:

      * ``</audio>`` ends the audio. Everything after it is ignored.
      * A token outside the unit range is a stray. The partial frame is dropped
        and assembly waits for the next frame boundary.
      * A token whose quantizer index is not the next one expected is off the
        round robin. The partial frame is dropped -- but if that token is itself
        a quantizer-0 token it *starts* the next frame rather than being thrown
        away, so one bad token costs one frame and not the rest of the clip.

    Incomplete trailing frames are not returned; they are not decodable.
    """
    first, last = layout.first_unit_id, layout.last_unit_id
    quantizers, end_id = layout.num_quantizers, layout.audio_end_token_id

    frames: list[list[int]] = []
    frame: list[int] = []
    for raw in token_ids:
        tid = int(raw)
        if tid == end_id:
            break
        if not first <= tid <= last:
            frame = []
            continue
        code, quantizer = divmod(tid - first, quantizers)
        if quantizer == len(frame):
            frame.append(code)
            if len(frame) == quantizers:
                frames.append(frame)
                frame = []
        else:
            frame = [code] if quantizer == 0 else []
    return frames


def unit_token(code: int, quantizer: int, layout: CodecLayout) -> int:
    """The id carrying ``code`` at ``quantizer``. The inverse of the divmod above.

    Only tests and tooling need this, but having the inverse in the same file as
    the forward direction is what makes the forward direction checkable.
    """
    if not 0 <= code < layout.codebook_size:
        raise ValueError(f"code {code} outside 0..{layout.codebook_size - 1}")
    if not 0 <= quantizer < layout.num_quantizers:
        raise ValueError(f"quantizer {quantizer} outside 0..{layout.num_quantizers - 1}")
    return layout.first_unit_id + code * layout.num_quantizers + quantizer


def codes_tensor(frames: list[list[int]]):
    """Frames -> the ``[1, num_quantizers, num_frames]`` tensor MimiModel.decode wants.

    Imported lazily so the arithmetic above stays testable without torch.
    """
    import torch

    return torch.tensor(frames, dtype=torch.long).T.unsqueeze(0)
