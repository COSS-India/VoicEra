"""Register rumik-oss-1 with vLLM as the Cohere2 it is, minus two tensors.

vLLM resolves a checkpoint to a model class by the name in `config.json`'s
`architectures`, and `RumikOSSForCausalLM` is not in its registry. The first
attempt handled that with `hf_overrides={"architectures":
["Cohere2ForCausalLM"]}`, which resolved correctly -- and then died loading
weights:

    ValueError: There is no module or parameter named 'stop_predictor'
    in CohereForCausalLM

The checkpoint carries a stop head that vLLM has no use for. We established on
hardware that the head is redundant -- disable it and the model still emits
`</audio>` by itself every time -- so the tensors are not needed. They just have
to stop being an error, and vLLM's `AutoWeightsLoader` raises on any name the
module does not have.

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
this folder being pip-installed in the image.

The cost is that adding or renaming this file needs an image rebuild, not just
a container restart -- unlike everything else here, which is bind-mounted.
"""
from __future__ import annotations

#: Tensors present in the checkpoint that vLLM's Cohere2 implementation has no
#: module for. Prefix rather than exact names: the head is an nn.Sequential, so
#: its parameters are stop_predictor.0.weight, .0.bias, .1.weight, and so on,
#: and enumerating them would break the day upstream adds a layer to it.
DROP_PREFIXES = ("stop_predictor.",)


def _model_class():
    from vllm.model_executor.models.commandr import CohereForCausalLM

    class RumikOSSForCausalLM(CohereForCausalLM):
        """Cohere2, plus a stop head this server does not use.

        Everything about the transformer is upstream's -- the architecture is
        `Cohere2ForCausalLM` and `RumikOSSForCausalLM` subclasses it adding only
        the head. So the whole of this class is dropping the head's weights on
        the way past and letting vLLM's own implementation do the rest.
        """

        def load_weights(self, weights, *args, **kwargs):
            kept = (
                (name, tensor)
                for name, tensor in weights
                if not name.startswith(DROP_PREFIXES)
            )
            return super().load_weights(kept, *args, **kwargs)

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
