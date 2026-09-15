"""Token production through vLLM, for the concurrency the Python loop cannot reach.

The transformers path runs upstream's hand-written decode loop: one 3B forward
per token, eager, no CUDA graphs, no batching. Measured on an H200 that is ~45
tok/s against the 100 tok/s a single realtime stream needs -- 22 ms per token
against a ~1.4 ms memory-bound floor, so roughly fifteen times more overhead
than arithmetic. Overhead-bound is the good case: a batch of fifty costs barely
more per step than a batch of one, which is the headroom vLLM harvests.

--------------------------------------------------------------------------
Why this needs no custom model class

`RumikOSSForCausalLM` subclasses `Cohere2ForCausalLM` and adds exactly one
thing: a `stop_predictor` head. vLLM already implements Cohere2 --
`"Cohere2ForCausalLM": ("commandr", "CohereForCausalLM")` in its registry -- so
the transformer body needs nothing written.

The head looked load-bearing and is not. Upstream's loop has two independent
stop paths: the sigmoid head, and the model emitting `</audio>`, which
`audio_token_ids()` explicitly includes in the allowed set. Disabling the head
on hardware and generating three times, the model emitted `</audio>` itself
every time, at 321-369 tokens against 273-361 with the head on. It is
belt-and-braces. So every behaviour of that loop maps onto a sampling
parameter:

    upstream                                vLLM
    ------------------------------------    -----------------------------
    allowed_ids = units + </audio>          allowed_token_ids
    break on </audio>                       stop_token_ids
    mask </audio> for min_new_tokens        min_tokens
    temperature / top_k multinomial         temperature / top_k
    max_new_tokens                          max_tokens

and the stop head is simply not used.

--------------------------------------------------------------------------
What hf_overrides does, and what it does not

`hf_overrides={"architectures": ["Cohere2ForCausalLM"]}` is what makes vLLM
resolve this checkpoint to its own `commandr` implementation instead of looking
for a `RumikOSSForCausalLM` it has never heard of. That part works, and it is
why no model class had to be written.

`trust_remote_code=True` is still required, and the first attempt without it
failed at startup. The override is applied AFTER the config is loaded; the
refusal happens DURING loading, because config.json carries an `auto_map` and
transformers gates any such repo behind the flag before an override can reach
it. So the flag is not optional here -- it is the price of reading the config
at all.

It is narrower than it sounds. With `architectures` overridden, the only
remote file transformers imports is `configuration_rumik_oss.py`, a
`Cohere2Config` subclass adding five integers. `modeling_rumik_oss.py` -- the
hand-written decode loop and the stop head -- is never imported, which is the
part that mattered: this folder still does not depend on that file continuing
to import cleanly against whichever `transformers` vLLM pins.

What it does cost is the frame arithmetic, which `codec.py` now owns and
`tests/test_rumik_codec.py` pins.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator

from codec import CodecLayout
from config import Config

log = logging.getLogger("rumik.vllm")


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
        # 16,385 ids, built once. Rebuilding per request would be 16k list
        # elements of garbage per synthesis for a value that never changes.
        self._allowed = layout.allowed_token_ids()

    async def start(self) -> None:
        # Imported here, not at module scope: the transformers path must stay
        # usable in an image without vLLM, and this module is imported by
        # engine.py either way.
        from vllm import AsyncEngineArgs, AsyncLLMEngine

        cfg = self.cfg
        args = AsyncEngineArgs(
            model=cfg.model_path,
            dtype=cfg.dtype,
            max_model_len=cfg.max_model_len,
            gpu_memory_utilization=cfg.gpu_memory_utilization,
            max_num_seqs=cfg.max_num_seqs,
            enforce_eager=cfg.enforce_eager,
            # Required, not preferred -- see the module docstring. config.json
            # has an auto_map, and transformers refuses to read such a repo
            # without this, before hf_overrides can be applied. Only the config
            # class is imported; the architecture override below is what keeps
            # vLLM on its own Cohere2 implementation rather than the
            # checkpoint's decode loop.
            trust_remote_code=True,
            hf_overrides={"architectures": ["Cohere2ForCausalLM"]},
        )
        log.info(
            "starting vLLM: %s dtype=%s max_len=%d gpu_util=%.2f max_seqs=%d eager=%s",
            cfg.model_path, cfg.dtype, cfg.max_model_len, cfg.gpu_memory_utilization,
            cfg.max_num_seqs, cfg.enforce_eager,
        )
        self._engine = AsyncLLMEngine.from_engine_args(args)

    async def stop(self) -> None:
        engine, self._engine = self._engine, None
        if engine is not None and hasattr(engine, "shutdown_background_loop"):
            engine.shutdown_background_loop()

    def sampling_params(self, *, max_new_tokens: int, temperature: float, top_k: int):
        from vllm import SamplingParams

        return SamplingParams(
            temperature=temperature,
            top_k=top_k,
            max_tokens=max_new_tokens,
            # Upstream masks </audio> for its first min_new_tokens steps; below
            # one frame's worth of tokens the model can stop before a single
            # complete frame exists and the response is empty.
            min_tokens=self.cfg.min_new_tokens,
            allowed_token_ids=self._allowed,
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
