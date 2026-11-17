"""Register rumik-oss-1 with vLLM as the Cohere2 it is, plus its stop head.

vLLM resolves a checkpoint to a model class by the name in `config.json`'s
`architectures`, and `RumikOSSForCausalLM` is not in its registry. Upstream's
class is `Cohere2ForCausalLM` plus exactly one module, a `stop_predictor` head,
so this plugin registers a subclass of vLLM's own Cohere2 implementation that
adds that head back, constrains sampling to the audio vocabulary, and does
nothing else.

--------------------------------------------------------------------------
Why the stop head is kept

The first vLLM build dropped the head's tensors, on the grounds that the model
emits `</audio>` by itself. It does -- but later: with the head disabled the
same prompts ran 321-369 tokens against 273-361 with it on, i.e. up to ~0.5 s
of extra tail per utterance. Upstream's `generate_audio` stops primarily on the
head, so dropping it is a behavioural change from the reference, not a
simplification.

Upstream's rule, per step, once `step >= min_new_tokens`:

    stop = sigmoid(stop_predictor(hidden_states[-1][:, -1])) > 0.5  -> </audio>

`hidden_states[-1]` there is the final, post-norm hidden state (transformers
replaces the last recorded layer output with `last_hidden_state`), at the last
position -- which is exactly the tensor vLLM hands `compute_logits`: the output
of `CohereModel.norm`, gathered at the positions being sampled. So the head runs
there, on the whole batch at once, and a row that wants to stop gets its
`</audio>` logit lifted far above every other allowed id.

It is lifted, not made the only finite value. vLLM's `min_tokens` masks
`</audio>` AFTER this method for the opening steps, and a row left with nothing
but -inf would sample NaN. Lifted, the mask simply wins and sampling continues
normally -- which is upstream's `step >= min_new_tokens` guard, reproduced by
vLLM's own machinery.

`RUMIK_STOP_HEAD=false` turns it off, so the two behaviours can be compared.

--------------------------------------------------------------------------
Why this is a plugin and not three lines in vllm_backend.py

`ModelRegistry.register_model()` in our process would not reach the engine.
vLLM runs `EngineCore` in a SEPARATE process, and the startup log says why it
cannot be forked:

    We must use the `spawn` multiprocessing start method...
    Reasons: CUDA is initialized

`spawn` gives the child a fresh interpreter that never imports our server, so a
registration made here is invisible there. vLLM's plugin system exists for
exactly this: entry points in the `vllm.general_plugins` group are loaded by
every vLLM process, parent and worker alike. Hence pyproject.toml, and hence
this folder being pip-installed (editable) in the image.

The same reason is why `RUMIK_STOP_HEAD` is read here, from the environment,
rather than passed in from config.py: the spawned worker inherits the
environment and nothing else.
"""
from __future__ import annotations

import functools
import os

#: Checkpoint tensors belonging to the stop head: stop_predictor.{0,1,3}.* for
#: an nn.Sequential(LayerNorm, Linear, GELU, Linear). Loaded when the head is
#: on; discarded when it is off -- vLLM's loader raises on any name the module
#: does not have, so "off" still has to consume them.
STOP_HEAD_PREFIX = "stop_predictor."

#: Upstream's threshold: `torch.sigmoid(...) > 0.5`.
STOP_THRESHOLD = 0.5

#: How far above the row's best logit `</audio>` is lifted when the head fires.
#: At temperature 0.8 a gap of 1e4 leaves every other id at exp(-12500), which
#: is zero. Finite on purpose -- see the module docstring.
STOP_BOOST = 1.0e4

_TRUE = {"1", "true", "yes", "on"}


def stop_head_enabled() -> bool:
    """RUMIK_STOP_HEAD, default on. Read in whichever process builds the model."""
    raw = os.getenv("RUMIK_STOP_HEAD")
    return True if raw is None or not raw.strip() else raw.strip().lower() in _TRUE


@functools.cache
def _model_class():
    """Built once per process.

    Cached so that every lookup vLLM makes -- registry inspection, then the
    actual load -- sees the same class object rather than a fresh one each time.
    """
    import torch
    from torch import nn
    from vllm.model_executor.models.commandr import CohereForCausalLM

    class RumikOSSForCausalLM(CohereForCausalLM):
        """Cohere2, plus upstream's stop head and the audio-vocabulary constraint.

        Everything about the transformer is upstream's -- the architecture is
        `Cohere2ForCausalLM` and `RumikOSSForCausalLM` subclasses it adding only
        the head. So this class does three small things and delegates the rest.
        """

        def __init__(self, *, vllm_config, prefix: str = ""):
            super().__init__(vllm_config=vllm_config, prefix=prefix)
            self._rumik_stop_head = stop_head_enabled()
            if self._rumik_stop_head:
                # Shape copied from modeling_rumik_oss.py layer for layer, so the
                # checkpoint's stop_predictor.{0,1,3}.* names land on it and
                # vLLM's default loader fills it with no custom code.
                hidden = int(self.config.hidden_size)
                inner = max(64, hidden // 4)
                self.stop_predictor = nn.Sequential(
                    nn.LayerNorm(hidden),
                    nn.Linear(hidden, inner),
                    nn.GELU(),
                    nn.Linear(inner, 1),
                )

        def load_weights(self, weights, *args, **kwargs):
            if self._rumik_stop_head:
                loaded = super().load_weights(weights, *args, **kwargs)
                missing = [
                    name for name, _ in self.stop_predictor.named_parameters()
                    if f"{STOP_HEAD_PREFIX}{name}" not in loaded
                ]
                if missing:
                    # Not a warning: an unloaded head is random weights, and a
                    # random head fires on arbitrary steps and truncates speech.
                    raise ValueError(
                        f"RUMIK_STOP_HEAD is on but the checkpoint did not supply "
                        f"stop_predictor.{missing}. Set RUMIK_STOP_HEAD=false or "
                        f"re-fetch the weights."
                    )
                return loaded
            kept = (
                (name, tensor)
                for name, tensor in weights
                if not name.startswith(STOP_HEAD_PREFIX)
            )
            return super().load_weights(kept, *args, **kwargs)

        def _audio_mask(self, logits):
            """True for every id the model may emit inside an <audio> span.

            Built once per device and cached. Sized from the logits rather than
            from `vocab_size`, because vLLM pads the vocabulary for tensor
            parallelism -- indices past the real end stay False, which is what
            we want anyway.
            """
            width = int(logits.shape[-1])
            cached = getattr(self, "_rumik_audio_mask", None)
            if (cached is not None and cached.device == logits.device
                    and int(cached.shape[-1]) == width):
                return cached
            config = self.config
            mask = torch.zeros(width, dtype=torch.bool, device=logits.device)
            mask[int(config.first_unit_id):int(config.last_unit_id) + 1] = True
            mask[int(config.audio_end_token_id)] = True
            self._rumik_audio_mask = mask
            return mask

        def compute_logits(self, hidden_states, *args, **kwargs):
            """Restrict sampling to the audio vocabulary, then apply the stop head.

            Upstream's loop builds a full -inf tensor and index_copy-ies the
            allowed scores into it, once per token. The obvious vLLM translation
            is SamplingParams.allowed_token_ids -- and that is capped at 1024
            entries, against the 16,385 this model needs:

                ValueError: Too many allowed token IDs: 16385. The max size is 1024.

            So the mask lives here instead, where it is one fused masked_fill
            over a tensor the engine already has, applied to the whole batch at
            once rather than per request. `</audio>` stays allowed; vLLM's own
            `min_tokens` then masks it for the opening frames, which is exactly
            what upstream's `step < min_new_tokens` branch did.
            """
            logits = super().compute_logits(hidden_states, *args, **kwargs)
            if logits is None:
                return logits
            logits = logits.masked_fill(~self._audio_mask(logits), float("-inf"))
            if self._rumik_stop_head:
                logits = self._apply_stop_head(hidden_states, logits)
            return logits

        def _apply_stop_head(self, hidden_states, logits):
            """Lift `</audio>` on every row whose stop head says stop."""
            head = self.stop_predictor
            h = hidden_states.to(dtype=head[1].weight.dtype)
            stop = torch.sigmoid(head(h).squeeze(-1).float()) > STOP_THRESHOLD
            end = int(self.config.audio_end_token_id)
            lifted = (logits.amax(dim=-1).float() + STOP_BOOST).to(logits.dtype)
            column = torch.where(stop, lifted, logits[:, end])
            # A new tensor rather than an in-place write: the tensor
            # masked_fill returned is ours, but not relying on that keeps this
            # safe if the order above ever changes.
            logits = logits.clone()
            logits[:, end] = column
            return logits

    return RumikOSSForCausalLM


def register() -> None:
    """Entry point. Called by vLLM in every process, including spawned workers."""
    from vllm import ModelRegistry

    # The lazy "<module>:<class>" form, which is what vLLM documents for
    # out-of-tree models: it defers importing torch and CUDA until the class is
    # actually needed, which is what keeps a forked or spawned worker from
    # initialising CUDA at import time.
    ModelRegistry.register_model(
        "RumikOSSForCausalLM", "rumik_vllm_plugin:RumikOSSForCausalLM"
    )


# Resolved on attribute access so the lazy registration above can find it
# without importing vllm at module import time.
def __getattr__(name: str):
    if name == "RumikOSSForCausalLM":
        return _model_class()
    raise AttributeError(name)
