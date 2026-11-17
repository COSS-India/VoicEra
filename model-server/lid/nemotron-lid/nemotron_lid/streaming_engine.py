"""
Cache-aware Nemotron streaming ASR helpers + encode/decode split.

Language prompt and VocabSlicer apply AFTER the encoder. The encoder itself is
language-agnostic, which lets auto-LID run on pre-prompt frames and then decode
those same frames without re-encoding.
"""

from __future__ import annotations

import os
import types
from typing import Optional

import torch

from .nemotron_lid_asr import install_hydra_patch

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
MAX_BATCH = int(os.environ.get("ASR_MAX_BATCH", "8"))


def _parse_att_context(raw: str) -> list[int]:
    parts = [p for p in raw.replace("[", "").replace("]", "").split(",") if p.strip()]
    if len(parts) != 2:
        raise ValueError(f"ASR_ATT_CONTEXT must be 'left,right', got {raw!r}")
    return [int(p) for p in parts]


ATT_CONTEXT = _parse_att_context(os.environ.get("ASR_ATT_CONTEXT", "96,7"))

# Wire code → prompt_dictionary key for this checkpoint (same as model-server).
LANGUAGE_PROMPT_MAP: dict[str, str] = {
    "bn": "bn",
    "gu": "gu",
    "hi": "hi",
    "kn": "kn",
    "ml": "ml",
    "mr": "mr",
    "pa": "pa",
    "ta": "ta",
    "te": "te",
    "en": "en",
    "ur": "ur",
}


def _install_prompt_apply(model) -> None:
    """Same post-encoder prompt injection used by production streaming ASR."""

    def _apply(self, encoded):
        if not self.concat or not hasattr(self, "_inference_prompt_index"):
            return encoded
        encoded = encoded.transpose(1, 2)
        batch, steps, _ = encoded.shape
        prompt = torch.zeros(
            batch, steps, self.num_prompts, dtype=encoded.dtype, device=encoded.device
        )
        idx = self._inference_prompt_index
        if torch.is_tensor(idx):
            idx = idx.to(device=encoded.device, dtype=torch.long)
        else:
            idx = torch.full((batch,), int(idx), dtype=torch.long, device=encoded.device)
        prompt.scatter_(2, idx.view(batch, 1, 1).expand(-1, steps, -1), 1.0)
        out_dtype = encoded.dtype
        encoded = self.prompt_kernel(torch.cat([encoded, prompt], dim=-1)).to(out_dtype)
        return encoded.transpose(1, 2)

    model._apply_prompt_to_encoded = types.MethodType(_apply, model)


class VocabSlicer:
    """Restrict RNNT/CTC logits to one language's multisoftmax slice."""

    def __init__(self, model, name: str = "nemotron-lid"):
        self.name = name
        self.active_lang = "<unset>"
        self.enabled = True
        self.calls = 0

        tokenizer = model.tokenizer
        offsets = getattr(tokenizer, "token_id_offset", None)
        if not offsets:
            raise RuntimeError(f"[{name}] tokenizer has no token_id_offset")
        self.offsets = dict(offsets)

        dec_cfg = model.cfg.decoder
        self.vocab_per_lang = int(dec_cfg.get("vocab_per_lang", 0) or 0)
        self.num_langs = int(dec_cfg.get("num_langs", 0) or 0) or len(self.offsets)
        if not self.vocab_per_lang:
            self.vocab_per_lang = len(tokenizer.vocab) // self.num_langs

        device = next(model.parameters()).device
        self._heads: list = []
        for layer in reversed(list(model.joint.joint_net)):
            if isinstance(layer, torch.nn.Linear):
                self._attach(layer, layer.out_features, channels_dim=False, device=device)
                break
        ctc = getattr(model, "ctc_decoder", None)
        if ctc is not None and hasattr(ctc, "decoder_layers"):
            for layer in reversed(list(ctc.decoder_layers)):
                if isinstance(layer, torch.nn.Conv1d):
                    self._attach(layer, layer.out_channels, channels_dim=True, device=device)
                    break
        if not self._heads:
            raise RuntimeError(f"[{name}] no output layer to slice")

    def _attach(self, module, out_features: int, channels_dim: bool, device):
        mask = torch.zeros(MAX_BATCH, out_features, device=device)

        def hook(_mod, _inp, out, _v=out_features, _ch=channels_dim, _slot=len(self._heads)):
            self.calls += 1
            batch = out.size(0)
            mask_t = self._heads[_slot][0]
            if batch > mask_t.size(0):
                grown = torch.zeros(batch, _v, device=mask_t.device, dtype=mask_t.dtype)
                grown[: mask_t.size(0)] = mask_t
                self._heads[_slot] = (grown, _v)
                mask_t = grown
            rows = mask_t[:batch]
            return out + (
                rows.view(batch, _v, 1)
                if _ch
                else rows.view(batch, *([1] * (out.dim() - 2)), _v)
            )

        self._heads.append((mask, out_features))
        module.register_forward_hook(hook)

    def _write_row(self, mask, out_features: int, row: int, lang: Optional[str]):
        if lang is None:
            mask[row].fill_(0.0)
        else:
            lo = self.offsets[lang]
            mask[row].fill_(float("-inf"))
            mask[row, lo : lo + self.vocab_per_lang] = 0.0
            mask[row, out_features - 1] = 0.0

    def set_language(self, lang: Optional[str]):
        if not self.enabled or lang == self.active_lang:
            return
        if lang is not None and lang not in self.offsets:
            raise ValueError(f"[{self.name}] no slice for {lang!r}")
        for mask, out_features in self._heads:
            for row in range(mask.size(0)):
                self._write_row(mask, out_features, row, lang)
        self.active_lang = lang


def configure_streaming_asr(model, name: str = "nemotron-lid"):
    """RNNT + vocab slice + prompt hook + streaming att context. Encoder weights untouched."""
    from nemo.collections.asr.parts.submodules.rnnt_decoding import RNNTDecodingConfig

    decoding_cfg = RNNTDecodingConfig(fused_batch_size=-1)
    if hasattr(decoding_cfg, "greedy"):
        decoding_cfg.greedy.use_cuda_graph_decoder = False
    model.change_decoding_strategy(decoding_cfg, decoder_type="rnnt")

    if hasattr(model.joint, "set_fuse_loss_wer"):
        model.joint.set_fuse_loss_wer(False)
    if hasattr(model.joint, "set_fused_batch_size"):
        model.joint.set_fused_batch_size(-1)

    supported = getattr(model.encoder, "att_context_size_all", None)
    if supported is not None and list(ATT_CONTEXT) not in [list(a) for a in supported]:
        raise ValueError(f"[{name}] att_context {ATT_CONTEXT} not in {supported}")
    model.encoder.set_default_att_context_size(att_context_size=ATT_CONTEXT)

    if hasattr(model.decoding, "set_strip_lang_tags"):
        model.decoding.set_strip_lang_tags(True)
    if hasattr(model.preprocessor, "featurizer"):
        model.preprocessor.featurizer.dither = 0.0

    model.eval()
    model.freeze()
    model._vocab_slicer = VocabSlicer(model, name=name)
    _install_prompt_apply(model)

    # Count encoder forwards for the "encode once" invariant.
    model._encoder_stream_forwards = 0
    enc = model.encoder
    if not getattr(enc, "_auto_lid_counter_installed", False):
        if hasattr(enc, "cache_aware_stream_step"):
            _orig = enc.cache_aware_stream_step

            def _counted(*args, **kwargs):
                model._encoder_stream_forwards += 1
                return _orig(*args, **kwargs)

            enc.cache_aware_stream_step = _counted  # type: ignore[method-assign]
        enc._auto_lid_counter_installed = True

    return model


def load_streaming_asr(nemo_path, device: str | None = None):
    """Load checkpoint configured for cache-aware streaming ASR (+ LID reuse)."""
    install_hydra_patch()
    import nemo.collections.asr as nemo_asr

    device = device or DEVICE
    print(f"[load] streaming ASR: {nemo_path} device={device}")
    try:
        model = nemo_asr.models.ASRModel.restore_from(str(nemo_path), map_location=device, strict=True)
    except RuntimeError as e:
        msg = str(e)
        if "Missing key(s)" in msg or "size mismatch" in msg:
            raise
        if "Unexpected key(s)" not in msg:
            raise
        print(f"[load] ignoring unused checkpoint tensors (strict=False)")
        model = nemo_asr.models.ASRModel.restore_from(str(nemo_path), map_location=device, strict=False)
    return configure_streaming_asr(model)


def get_streaming_params(model) -> dict:
    cfg = model.encoder.streaming_cfg

    def as_pair(v):
        return list(v) if isinstance(v, (list, tuple)) else [v, v]

    pre_encode = getattr(model.encoder, "pre_encode", None)
    if pre_encode is not None and hasattr(pre_encode, "get_sampling_frames"):
        sampling_frames = as_pair(pre_encode.get_sampling_frames())
    else:
        sampling_frames = [1, 1]

    return {
        "chunk_size": as_pair(cfg.chunk_size),
        "shift_size": as_pair(cfg.shift_size),
        "pre_encode_cache_size": as_pair(cfg.pre_encode_cache_size),
        "drop_extra_pre_encoded": int(cfg.drop_extra_pre_encoded),
        "sampling_frames": sampling_frames,
        "hop_length": int(
            round(model.cfg.preprocessor.window_stride * model.cfg.preprocessor.sample_rate)
        ),
        "feat_in": int(model.encoder._feat_in),
    }


def get_initial_cache(model, batch_size: int = 1):
    return model.encoder.get_initial_cache_state(batch_size=batch_size)


def prompt_index(model, target_lang: str) -> int:
    return int(model.cfg.model_defaults.get("prompt_dictionary", {})[target_lang])


def configure_decoder_language(model, target_lang: str) -> None:
    """
    Set prompt + VocabSlicer for decoding. Does NOT touch encoder caches / session state.

    target_lang is required only here (post-encoder), never as an encoder input.
    """
    prompt_dict = model.cfg.model_defaults.get("prompt_dictionary", {})
    if target_lang not in prompt_dict:
        raise ValueError(f"Unknown target language {target_lang!r}")
    slicer = getattr(model, "_vocab_slicer", None)
    if slicer is not None:
        slicer.set_language(target_lang)
    if getattr(model, "_inference_prompt_index", None) != prompt_dict[target_lang]:
        model._inference_prompt_index = prompt_dict[target_lang]


def resolve_prompt_lang(lang_code: str) -> str:
    clean = lang_code.strip().lower()
    if clean == "auto":
        raise ValueError("auto has no fixed prompt; run LID first")
    if clean not in LANGUAGE_PROMPT_MAP:
        raise ValueError(f"Unsupported language code {clean!r}")
    return LANGUAGE_PROMPT_MAP[clean]


@torch.inference_mode()
def stream_encode_step(
    model,
    processed_signal: torch.Tensor,
    processed_signal_length: torch.Tensor,
    cache_channel: torch.Tensor,
    cache_time: torch.Tensor,
    cache_len: torch.Tensor,
    *,
    keep_all_outputs: bool = False,
    drop_extra: int = 0,
):
    """
    Encoder-only half of conformer_stream_step.

    Returns pre-prompt encoded frames + updated streaming caches.
    Does not apply language prompt and does not run the RNNT decoder.
    """
    (
        encoded,
        encoded_len,
        cache_channel_next,
        cache_time_next,
        cache_len_next,
    ) = model.encoder.cache_aware_stream_step(
        processed_signal=processed_signal,
        processed_signal_length=processed_signal_length,
        cache_last_channel=cache_channel,
        cache_last_time=cache_time,
        cache_last_channel_len=cache_len,
        keep_all_outputs=keep_all_outputs,
        drop_extra_pre_encoded=drop_extra,
    )
    return encoded, encoded_len, cache_channel_next, cache_time_next, cache_len_next


@torch.inference_mode()
def stream_decode_encoded(
    model,
    encoded: torch.Tensor,
    encoded_len: torch.Tensor,
    target_lang: str,
    previous_hypotheses=None,
):
    """
    Decoder half: apply language prompt to already-computed encoder frames → RNNT.

    Does not call the encoder.
    """
    configure_decoder_language(model, target_lang)
    prompted = model._apply_prompt_to_encoded(encoded)
    best_hyp = model.decoding.rnnt_decoder_predictions_tensor(
        encoder_output=prompted,
        encoded_lengths=encoded_len,
        return_hypotheses=True,
        partial_hypotheses=previous_hypotheses,
    )
    hyp = best_hyp[0]
    text = (hyp.text or "") if hasattr(hyp, "text") else str(hyp)
    return text.strip(), [hyp], [hyp.y_sequence]


def extract_transcription_text(transcriptions) -> str:
    if not transcriptions:
        return ""
    t = transcriptions[0]
    if hasattr(t, "text"):
        return (t.text or "").strip()
    return str(t).strip()
