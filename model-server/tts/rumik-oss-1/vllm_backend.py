"""Token production through vLLM, for the concurrency the Python loop cannot reach.

The transformers path runs upstream's hand-written decode loop: one 3B forward
per token, eager, no CUDA graphs, no batching. Measured on an H200 that is ~45
tok/s against the 100 tok/s a single realtime stream needs -- 22 ms per token
against a ~1.4 ms memory-bound floor, so roughly fifteen times more overhead
than arithmetic. Overhead-bound is the good case: a batch of fifty costs barely
more per step than a batch of one, which is the headroom vLLM harvests.

--------------------------------------------------------------------------
How upstream's loop maps onto vLLM

`RumikOSSForCausalLM` is `Cohere2ForCausalLM` plus one `stop_predictor` head,
and vLLM already implements Cohere2 -- `"Cohere2ForCausalLM": ("commandr",
"CohereForCausalLM")` in its registry. rumik_vllm_plugin registers a subclass
of that implementation which adds the head back and the vocabulary mask, so
every behaviour of upstream's `generate_audio` has a counterpart:

    upstream                                vLLM
    ------------------------------------    -----------------------------------
    allowed_ids = units + </audio>          a mask in compute_logits (*)
    sigmoid(stop_predictor(h)) > 0.5        the same head, in compute_logits,
                                            lifting </audio> (RUMIK_STOP_HEAD)
    break on </audio>                       stop_token_ids
    mask </audio> for min_new_tokens        min_tokens
    temperature / top_k multinomial         temperature / top_k (top_p 1.0)
    max_new_tokens                          max_tokens

(*) not SamplingParams.allowed_token_ids, which is capped at 1024 entries
against the 16,385 this vocabulary needs.

--------------------------------------------------------------------------
How the checkpoint is resolved, after two wrong turns

1. Rewriting `architectures` to `Cohere2ForCausalLM` via `hf_overrides`
   resolved fine and then failed loading weights -- `there is no module or
   parameter named 'stop_predictor'`. vLLM's loader raises on any name the
   module does not have. The plugin's class now HAS that module.
2. Registering the class from this process would not have helped either.
   vLLM runs EngineCore in a SPAWNED process ("We must use the `spawn`
   multiprocessing start method ... CUDA is initialized"), which never imports
   our server. Hence an entry point, and hence this folder being pip-installed.

`trust_remote_code=True` is required on top, and not optional: config.json
carries an `auto_map`, and transformers refuses to read such a repo without the
flag. It is narrower than it sounds. The only remote file imported is
`configuration_rumik_oss.py`, a `Cohere2Config` subclass adding a handful of
fields; `modeling_rumik_oss.py`, with the hand-written decode loop, is never
imported, so this folder does not depend on that file importing cleanly against
whichever `transformers` vLLM pins.

What it does cost is the frame arithmetic, which `codec.py` now owns and
`tests/test_rumik_codec.py` pins.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from codec import CodecLayout
from config import Config

log = logging.getLogger("rumik.vllm")

_GIB = 1024 ** 3

#: What vLLM needs on top of the weights before it can hold a single sequence:
#: CUDA graphs, activations for the profiling pass, the sampler's logits over a
#: 277k vocabulary, and a first slice of KV cache. Measured on this model at
#: 0.12 of an H200 (17 GB): 10.06 GiB of KV left after 6.76 GB of weights, so
#: the overhead there was well under this. Generous rather than tight on
#: purpose -- the check exists to turn a guaranteed failure into a readable one,
#: not to predict vLLM's profiler.
_ENGINE_OVERHEAD_BYTES = 3 * _GIB


def weights_bytes(model_path: str) -> int | None:
    """Size of the checkpoint's top-level safetensors shards; None if not a directory.

    Top level only: `codec/` holds Mimi, which vLLM never loads.
    """
    root = Path(model_path)
    if not root.is_dir():
        return None
    return sum(p.stat().st_size for p in root.glob("*.safetensors")) or None


def check_memory_budget(*, total_bytes: int, fraction: float, weights: int) -> None:
    """Refuse a RUMIK_GPU_MEMORY_UTILIZATION that cannot hold the model at all.

    The fraction is of the CARD'S TOTAL, and 0.12 was sized for a 143 GB H200.
    On a 24 GB card 0.12 is 2.9 GB, less than the weights alone, and vLLM then
    dies deep in its profiler with a message about KV cache blocks. Said here
    instead, in the operator's terms, with the number that would work.
    """
    budget = total_bytes * fraction
    need = weights + _ENGINE_OVERHEAD_BYTES
    if budget >= need:
        return
    suggested = min(0.95, round(need / total_bytes + 0.02, 2))
    raise RuntimeError(
        f"RUMIK_GPU_MEMORY_UTILIZATION={fraction} reserves {budget / _GIB:.1f} GiB of "
        f"this {total_bytes / _GIB:.0f} GiB GPU, but the weights alone are "
        f"{weights / _GIB:.1f} GiB and vLLM needs ~{_ENGINE_OVERHEAD_BYTES / _GIB:.0f} "
        f"GiB more before it can hold one sequence. The default 0.12 is sized for a "
        f"143 GB H200. Try RUMIK_GPU_MEMORY_UTILIZATION={suggested} or higher on this "
        f"card, leaving room for anything else sharing it."
    )


class VllmTokenSource:
    """An async stream of audio token ids, batched across every caller.

    One engine per process, many concurrent requests. vLLM's scheduler does the
    batching, so this class holds no admission logic of its own -- that is the
    slot's `RUMIK_MAX_CONCURRENCY`, which exists to bound KV memory and latency
    rather than to serialise work.
    """

    def __init__(self, cfg: Config, layout: CodecLayout) -> None:
        self.cfg = cfg
        self.layout = layout
        self._engine = None

    async def start(self) -> None:
        # Imported here, not at module scope: the transformers path must stay
        # usable in an image without vLLM, and this module is imported by
        # engine.py either way.
        from vllm import AsyncEngineArgs, AsyncLLMEngine

        cfg = self.cfg
        self._preflight_memory()
        args = AsyncEngineArgs(
            model=cfg.model_path,
            dtype=cfg.dtype,
            max_model_len=cfg.max_model_len,
            gpu_memory_utilization=cfg.gpu_memory_utilization,
            max_num_seqs=cfg.max_num_seqs,
            enforce_eager=cfg.enforce_eager,
            # Required, not preferred -- see the module docstring. config.json
            # carries an auto_map, and transformers refuses to read such a repo
            # without this. Only the config class is imported; the modeling code
            # is not.
            trust_remote_code=True,
            # No hf_overrides. The first attempt rewrote `architectures` to
            # Cohere2ForCausalLM, which resolved correctly and then failed
            # loading weights on the checkpoint's stop head. rumik_vllm_plugin
            # now registers RumikOSSForCausalLM under its real name, as a
            # subclass of vLLM's Cohere2 that carries that head -- so the
            # architecture in config.json is honoured rather than disguised.
        )
        log.info(
            "starting vLLM: %s dtype=%s max_len=%d gpu_util=%.2f max_seqs=%d eager=%s",
            cfg.model_path, cfg.dtype, cfg.max_model_len, cfg.gpu_memory_utilization,
            cfg.max_num_seqs, cfg.enforce_eager,
        )
        self._engine = AsyncLLMEngine.from_engine_args(args)

    def _preflight_memory(self) -> None:
        """See check_memory_budget. Skipped when there is nothing to measure."""
        import torch

        weights = weights_bytes(self.cfg.model_path)
        if weights is None or not torch.cuda.is_available():
            return
        # Device 0 of what this container can see, which is the card vLLM will use.
        total = int(torch.cuda.get_device_properties(0).total_memory)
        check_memory_budget(
            total_bytes=total, fraction=self.cfg.gpu_memory_utilization, weights=weights
        )

    async def stop(self) -> None:
        """Shut the engine down, which is what ends its spawned EngineCore process.

        `shutdown()` is the method this vLLM has (0.25's AsyncLLM). The previous
        code looked for V0's `shutdown_background_loop`, found nothing, and
        silently left the worker -- and its GPU reservation -- to be reaped with
        the container.
        """
        engine, self._engine = self._engine, None
        if engine is None:
            return
        shutdown = getattr(engine, "shutdown", None) or getattr(
            engine, "shutdown_background_loop", None
        )
        if shutdown is None:
            log.warning("vLLM engine has no shutdown method; leaving it to exit")
            return
        try:
            shutdown()
        except Exception:  # noqa: BLE001
            # Shutting down during container stop; a failure here must not
            # mask whatever stopped the server.
            log.exception("vLLM engine shutdown failed")

    def sampling_params(self, *, max_new_tokens: int, temperature: float, top_k: int):
        from vllm import SamplingParams

        return SamplingParams(
            temperature=temperature,
            top_k=top_k,
            max_tokens=max_new_tokens,
            # Upstream masks </audio> for its first min_new_tokens steps; below
            # one frame's worth of tokens the model can stop before a single
            # complete frame exists and the response is empty. This also
            # overrides the stop head for those steps, as upstream's
            # `step >= min_new_tokens` guard does.
            min_tokens=self.cfg.min_new_tokens,
            # NOT allowed_token_ids. vLLM caps that at 1024 entries and this
            # model's audio vocabulary is 16,385, so the first request died on
            # "Too many allowed token IDs: 16385. The max size is 1024." The
            # constraint is applied in the model's compute_logits instead --
            # one masked_fill over the whole batch rather than a per-request
            # allow-list. See rumik_vllm_plugin.
            stop_token_ids=[self.layout.audio_end_token_id],
            # Never text. Skipping the detokenizer is not only faster -- the
            # unit tokens would come back as `<code>_<quantizer>` strings that
            # this server would have to parse back into the integers it already
            # had.
            detokenize=False,
        )

    async def stream(self, prompt_token_ids: list[int], *, max_new_tokens: int,
                     temperature: float, top_k: int) -> AsyncIterator[int]:
        """Yield generated token ids as vLLM produces them.

        `RequestOutput.outputs[0].token_ids` is cumulative, so this diffs
        against what it has already emitted rather than re-yielding the run.

        Cancellation is the caller closing this generator -- barge-in, an
        error, anything. The `finally` aborts the vLLM request, which is what
        frees the GPU slot. On the transformers path that took a tap raising
        inside the model's own sampling loop, because a blocking Python loop in
        a worker thread cannot be stopped any other way. Here it is one call.
        """
        from vllm import TokensPrompt

        if self._engine is None:
            raise RuntimeError("vLLM engine is not started")

        request_id = str(uuid.uuid4())
        params = self.sampling_params(
            max_new_tokens=max_new_tokens, temperature=temperature, top_k=top_k
        )
        seen = 0
        try:
            generator = self._engine.generate(
                TokensPrompt(prompt_token_ids=prompt_token_ids), params, request_id
            )
            async for output in generator:
                tokens = output.outputs[0].token_ids
                for token in tokens[seen:]:
                    yield int(token)
                seen = len(tokens)
        finally:
            engine = self._engine
            if engine is not None:
                try:
                    await engine.abort(request_id)
                except Exception:  # noqa: BLE001
                    # Already finished, or the engine is going down. Aborting a
                    # request that has completed is not an error worth raising
                    # into a caller that has stopped listening anyway.
                    log.debug("abort of %s was a no-op", request_id)
