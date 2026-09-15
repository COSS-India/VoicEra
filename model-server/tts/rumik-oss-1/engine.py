"""rumik-oss-1: text -> 24 kHz PCM, streamed while it is generated.

The model emits Mimi codec tokens, eight per frame, frame-major:

    num_quantizers 8 x codebook_size 2048 = 16384 unit ids
    first_unit_id 261008 .. last_unit_id 277391      (from config.json)
    frame_rate_hz 12.5  ->  8 tokens = one frame = 80 ms = 1920 samples

So realtime is 100 tokens per second of speech, and that number is the bar
everything here is measured against.

--------------------------------------------------------------------------
Two backends, one interface

A token source yields generated ids; everything downstream -- frame assembly,
the windowed Mimi decode, the PCM -- is shared and does not know which produced
them.

`vllm` (default) serves the checkpoint as the `Cohere2ForCausalLM` it
structurally is, with continuous batching and CUDA graphs. See vllm_backend.py.

`transformers` runs upstream's own `generate_audio` -- a hand-written per-token
Python loop with no streamer, no callback and no LogitsProcessor. It is kept
because it is the reference: a fast model that sounds different is a failed
port, and the only way to know is to run both. Measured at ~45 tok/s against
the 100 tok/s bar, so it is not a serving option.

Streaming it needs a seam. That loop calls `self._constrained_sample(...)` once
per token, and `install_tap` wraps exactly that call, so upstream's loop runs
verbatim and only the token stream is tapped on its way past. The same seam is
the interrupt: the tap raises on its next call, unwinding the loop from the
inside, which is the only way to stop a blocking generation from outside its
own thread. Under vLLM none of that is needed -- aborting the request is a
method call.

--------------------------------------------------------------------------
Decoding while generating

Mimi's decoder in `transformers` has no streaming state to carry across calls
(the transformer KV could be cached; the convolution stack cannot), so frames
are decoded in a window and only the newest samples are kept:

    decode frames [total - new - RUMIK_DECODE_CONTEXT_FRAMES : total]
    emit the last  new * samples_per_frame  samples

`tests/` proves that tiles the clip exactly once, with no gap or repeat. The
leading frames are context whose only job is to make the emitted samples
identical to a single whole-clip decode.

**This is the next bottleneck, and it is known.** At the shipped defaults each
chunk decodes 34 frames to emit 2 -- 17x redundant. That is invisible while the
LM is the slow part and stops being invisible the moment vLLM is doing the
generating. Retune it against a measured single-stream RTF, not before.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import torch
from audio import SAMPLE_RATE
from codec import CodecLayout, codes_tensor, frames_from_tokens
from config import Config
from prompt import PromptError, build_prompt, check_text
from transformers import AutoFeatureExtractor, AutoTokenizer, MimiModel

log = logging.getLogger("rumik.engine")

_END = object()


class GenerationCancelled(Exception):
    """Raised inside the model's own sampling loop to abandon a stream."""


class TTSGenerationError(RuntimeError):
    """Generation failed. Distinct from PromptError, which is the caller's fault."""


# ---------------------------------------------------------------- the tap
class _TapBase:
    """What the sampling tap needs: somewhere to put tokens, and a stop flag."""

    def __init__(self) -> None:
        self.cancelled = threading.Event()

    def push(self, item: object) -> None:
        raise NotImplementedError


class _Tap(_TapBase):
    """One request's window into the model's sampling loop.

    Written from the worker thread, read on the event loop. The queue is fed
    through `call_soon_threadsafe`, so the consumer never polls.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._loop = loop
        self._queue: asyncio.Queue = asyncio.Queue()

    def push(self, item: object) -> None:
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, item)
        except RuntimeError:
            # The loop is closed; the caller is long gone. Raising here would
            # surface inside the model's loop as a generation failure.
            pass

    async def get(self) -> object:
        return await self._queue.get()


class _ListTap(_TapBase):
    """Collects tokens in-thread. Used by warmup, which has no consumer."""

    def __init__(self) -> None:
        super().__init__()
        self.tokens: list[int] = []

    def push(self, item: object) -> None:
        if item is not _END:
            self.tokens.append(int(item))  # type: ignore[arg-type]


_TAP: contextvars.ContextVar[_TapBase | None] = contextvars.ContextVar("rumik_tap", default=None)


def install_tap(model) -> None:
    """Wrap the model's per-token sampling call. Idempotent."""
    if getattr(model, "_rumik_tapped", False):
        return
    if not hasattr(model, "_constrained_sample"):
        raise TTSGenerationError(
            "this checkpoint's model class has no _constrained_sample, which is the "
            "per-token seam the transformers backend streams and cancels through."
        )
    original = model._constrained_sample

    def tapped(*args, **kwargs):
        tap = _TAP.get()
        if tap is not None and tap.cancelled.is_set():
            raise GenerationCancelled
        token = original(*args, **kwargs)
        if tap is not None:
            tap.push(int(torch.as_tensor(token).reshape(-1)[0].item()))
        return token

    model._constrained_sample = tapped
    model._rumik_tapped = True


# ---------------------------------------------------------------- stats
@dataclass
class StreamStats:
    """Timings for one synthesis request. Owned by the caller; never shared."""

    frame_ms: float = 80.0
    ttfa_ms: float | None = None
    tokens: int = 0
    frames: int = 0
    pcm_bytes: int = 0
    gen_ms: float = 0.0

    @property
    def audio_ms(self) -> float:
        return self.frames * self.frame_ms

    @property
    def rtf(self) -> float | None:
        """Generation time / audio duration. Below 1.0 is faster than realtime."""
        return round(self.gen_ms / self.audio_ms, 3) if self.audio_ms else None

    @property
    def tokens_per_s(self) -> float | None:
        return round(self.tokens / (self.gen_ms / 1000.0), 1) if self.gen_ms else None

    def summary(self) -> dict:
        return {
            "ttfa_ms": round(self.ttfa_ms, 1) if self.ttfa_ms is not None else None,
            "audio_ms": round(self.audio_ms, 1),
            "gen_ms": round(self.gen_ms, 1),
            "rtf": self.rtf,
            "tokens": self.tokens,
            "tokens_per_s": self.tokens_per_s,
        }


# ------------------------------------------------- the transformers backend
class TransformersTokenSource:
    """Upstream's `generate_audio`, tapped per token. The reference, not a server."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.model = None
        self.tokenizer = None

    async def start(self) -> None:
        await asyncio.to_thread(self._load)

    def _load(self) -> None:
        from transformers import AutoModelForCausalLM

        cfg = self.cfg
        dtype = getattr(torch, cfg.dtype, None)
        if not isinstance(dtype, torch.dtype):
            raise TTSGenerationError(f"RUMIK_DTYPE={cfg.dtype!r} is not a torch dtype")
        log.info("loading %s on %s (transformers, %s)", cfg.model_path, cfg.device, cfg.dtype)
        self.tokenizer = AutoTokenizer.from_pretrained(cfg.model_path, trust_remote_code=True)
        self.model = (
            AutoModelForCausalLM.from_pretrained(
                cfg.model_path, trust_remote_code=True, dtype=dtype,
                attn_implementation=cfg.attn_implementation,
            ).eval().to(cfg.device)
        )
        install_tap(self.model)

    async def stop(self) -> None:
        self.model = None

    def _generate_blocking(self, prompt_token_ids, max_new_tokens, temperature, top_k) -> None:
        """Run their loop. The result is discarded: the tap has the tokens."""
        device = self.model.device
        input_ids = torch.tensor([prompt_token_ids], dtype=torch.long, device=device)
        attention_mask = torch.ones_like(input_ids)
        with torch.inference_mode():
            self.model.generate_audio(
                input_ids=input_ids, attention_mask=attention_mask,
                max_new_tokens=max_new_tokens, min_new_tokens=self.cfg.min_new_tokens,
                temperature=temperature, top_k=top_k, do_sample=True,
            )

    async def stream(self, prompt_token_ids: list[int], *, max_new_tokens: int,
                     temperature: float, top_k: int) -> AsyncIterator[int]:
        tap = _Tap(asyncio.get_running_loop())
        holder = _TAP.set(tap)
        worker = asyncio.create_task(
            self._drive(tap, prompt_token_ids, max_new_tokens, temperature, top_k)
        )
        # Nobody awaits this on the cancellation path, and asyncio reports an
        # unretrieved exception as though the event loop itself were at fault.
        worker.add_done_callback(_retrieve)
        try:
            while True:
                item = await tap.get()
                if item is _END:
                    break
                yield int(item)  # type: ignore[arg-type]
            # _END is pushed from the worker's `finally`, so it can still be a
            # moment from done. Awaiting turns a failed generation into an error
            # rather than a stream that merely stopped early.
            await worker
        finally:
            tap.cancelled.set()
            _TAP.reset(holder)

    async def _drive(self, tap: _Tap, prompt_token_ids, max_new_tokens, temperature,
                     top_k) -> None:
        try:
            await asyncio.to_thread(
                self._generate_blocking, prompt_token_ids, max_new_tokens, temperature, top_k
            )
        except GenerationCancelled:
            log.info("generation cancelled by the caller")
        finally:
            tap.push(_END)


def _retrieve(task: asyncio.Task) -> None:
    """Mark a worker's exception as seen. Reporting happens at the await."""
    if not task.cancelled():
        task.exception()


# ---------------------------------------------------------------- the engine
class RumikTTSEngine:
    """Loads the checkpoint and turns requests into streamed PCM."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.layout: CodecLayout | None = None
        self.tokenizer = None
        self.mimi = None
        self.speakers: tuple[str, ...] = ()
        self.sample_rate = SAMPLE_RATE
        self.samples_per_frame = 1920
        self.frame_ms = 80.0
        self.quantizers = 8
        self.max_position_embeddings = cfg.max_model_len
        self._tokens = None
        self._slots = asyncio.Semaphore(cfg.max_concurrency)

    # ---------------------------------------------------------------- loading
    async def start(self) -> None:
        """Async because vLLM's engine binds to the running loop.

        The blocking parts -- the codec, the tokenizer, the transformers
        checkpoint -- go to a thread so /health can answer "loading" throughout.
        """
        cfg = self.cfg
        await asyncio.to_thread(self._load_shared)

        if cfg.engine == "vllm":
            from vllm_backend import VllmTokenSource

            self._tokens = VllmTokenSource(cfg, self.layout)
        else:
            self._tokens = TransformersTokenSource(cfg)
        await self._tokens.start()

        if cfg.engine == "transformers":
            # The tokenizer the tap path loaded knows the remote code; prefer it
            # so both paths tokenize identically when compared.
            self.tokenizer = self._tokens.tokenizer or self.tokenizer

        if cfg.warmup_enabled:
            await self._warmup()

    def _load_shared(self) -> None:
        """Everything both backends need: the layout, the codec, the tokenizer."""
        cfg = self.cfg
        dtype = getattr(torch, cfg.dtype, None)
        if not isinstance(dtype, torch.dtype):
            raise TTSGenerationError(f"RUMIK_DTYPE={cfg.dtype!r} is not a torch dtype")

        self.layout = CodecLayout.from_config(cfg.model_path)
        self.quantizers = self.layout.num_quantizers
        self.speakers = self.layout.speakers
        if not self.speakers:
            raise TTSGenerationError(
                "config.json declares no `speakers`. The voice roster is read from the "
                "checkpoint rather than hardcoded, so there is nothing to offer callers."
            )

        # No trust_remote_code: the tokenizer is a standard one, and the vLLM
        # path deliberately imports none of the checkpoint's code.
        self.tokenizer = AutoTokenizer.from_pretrained(cfg.model_path)

        self.mimi = (
            MimiModel.from_pretrained(f"{cfg.model_path}/codec", dtype=dtype)
            .eval().to(cfg.decoder_device)
        )
        rate = int(AutoFeatureExtractor.from_pretrained(f"{cfg.model_path}/codec").sampling_rate)
        if rate != SAMPLE_RATE:
            raise TTSGenerationError(
                f"the codec reports {rate} Hz but this folder is built around "
                f"{SAMPLE_RATE} Hz (audio.py, the WAV headers and X-Sample-Rate)."
            )
        self.sample_rate = rate

        # Measured, not assumed: decode a known number of all-zero frames (0 is a
        # valid Mimi code) and see how many samples come back. This is the number
        # the window slicing depends on.
        probe_frames = 8
        probe = torch.zeros(1, self.quantizers, probe_frames, dtype=torch.long)
        with torch.inference_mode():
            out = self.mimi.decode(probe.to(self.mimi.device)).audio_values
        self.samples_per_frame = int(out.shape[-1]) // probe_frames
        self.frame_ms = self.samples_per_frame / self.sample_rate * 1000.0
        log.info(
            "codec: %d quantizers, %d samples/frame (%.1f ms), %d Hz | engine=%s",
            self.quantizers, self.samples_per_frame, self.frame_ms, self.sample_rate,
            cfg.engine,
        )

    async def stop(self) -> None:
        if self._tokens is not None:
            await self._tokens.stop()

    async def _warmup(self) -> None:
        """One short synthesis, to pay the load costs before traffic.

        On the transformers path it also proves the sampling tap is still wired:
        a loop that stopped routing every token through `_constrained_sample`
        would otherwise first show up as a stream that produces nothing and
        looks like a wedged GPU.
        """
        prompt = build_prompt(voice=self.speakers[0], instructions="", text="नमस्ते")
        ids = self.tokenizer(prompt)["input_ids"]
        started = time.perf_counter()
        count = 0
        async for _ in self._tokens.stream(
            ids, max_new_tokens=max(self.quantizers, self.cfg.warmup_tokens),
            temperature=self.cfg.temperature, top_k=self.cfg.top_k,
        ):
            count += 1
        elapsed = (time.perf_counter() - started) * 1000.0
        if not count:
            raise TTSGenerationError(
                f"warmup produced no tokens on the {self.cfg.engine} backend."
            )
        log.info("warmup: %d tokens in %.0f ms (%.1f tok/s)",
                 count, elapsed, count / (elapsed / 1000.0))

    # ------------------------------------------------------------- the stream
    def _decode_new_frames(self, tokens: list[int], emitted: int,
                           *, flush: bool) -> tuple[bytes, int] | None:
        """PCM for whatever complete frames have appeared since `emitted`."""
        frames = frames_from_tokens(tokens, self.layout)
        total = len(frames)
        new = total - emitted
        if new <= 0 or (not flush and new < self.cfg.decode_chunk_frames):
            return None

        start = max(0, total - new - self.cfg.decode_context_frames)
        window = codes_tensor(frames[start:total]).to(self.mimi.device)
        with torch.inference_mode():
            wav = self.mimi.decode(window).audio_values[0, 0]
        keep = new * self.samples_per_frame
        fresh = wav[-keep:] if int(wav.shape[-1]) > keep else wav

        arr = fresh.float().cpu().clamp(-1.0, 1.0).numpy()
        return (arr * 32767.0).astype("<i2").tobytes(), total

    def plan(self, *, text: str, voice: str | None,
             instructions: str | None, max_new_tokens: int | None) -> tuple[list[int], int]:
        """Validate the request and return (prompt token ids, token budget).

        Separate from the generator so everything a caller can fix raises before
        the first byte and becomes a 400. Once a StreamingResponse has sent its
        status line the only way left to signal failure is to stop writing.
        """
        cfg = self.cfg
        chosen = (voice or cfg.default_voice).strip()
        if chosen not in self.speakers:
            raise PromptError(
                f"unknown voice {chosen!r}; this checkpoint has "
                f"{', '.join(self.speakers)} (see GET /v1/voices)"
            )
        described = cfg.default_instructions if instructions is None else instructions
        prompt = build_prompt(
            voice=chosen, instructions=described,
            text=check_text(text, cfg.max_input_chars),
        )
        prompt_ids = list(self.tokenizer(prompt)["input_ids"])

        # Audio tokens share the context window with the prompt, so a long
        # description shortens the utterance. Clamped here rather than left to
        # fail deep inside the engine as a position-embedding error.
        budget = self.max_position_embeddings - len(prompt_ids)
        if budget <= cfg.min_new_tokens:
            raise PromptError(
                f"the prompt uses {len(prompt_ids)} of {self.max_position_embeddings} "
                f"context positions, leaving no room for audio. Shorten `input` or "
                f"`instructions`."
            )
        cap = min(max_new_tokens or cfg.max_new_tokens_default, cfg.max_new_tokens_limit, budget)
        return prompt_ids, cap

    async def synthesize_stream(self, *, prompt_token_ids: list[int], max_new_tokens: int,
                                temperature: float | None, top_k: int | None,
                                stats: StreamStats):
        """Yield 24 kHz mono s16le PCM as it is generated.

        Backend-agnostic: it consumes token ids and knows nothing about which
        engine produced them.
        """
        cfg = self.cfg
        stats.frame_ms = self.frame_ms
        async with self._slots:
            tokens: list[int] = []
            emitted = 0
            started = time.perf_counter()
            try:
                async for token in self._tokens.stream(
                    prompt_token_ids, max_new_tokens=max_new_tokens,
                    temperature=temperature if temperature is not None else cfg.temperature,
                    top_k=top_k if top_k is not None else cfg.top_k,
                ):
                    tokens.append(token)
                    stats.tokens = len(tokens)
                    # Cheap gate: de-interleaving can drop tokens, so this only
                    # decides when it is worth asking.
                    if len(tokens) < (emitted + cfg.decode_chunk_frames) * self.quantizers:
                        continue
                    chunk = await asyncio.to_thread(
                        self._decode_new_frames, list(tokens), emitted, flush=False
                    )
                    if chunk is None:
                        continue
                    pcm, emitted = chunk
                    self._record(stats, started, emitted, pcm)
                    yield pcm

                tail = await asyncio.to_thread(
                    self._decode_new_frames, list(tokens), emitted, flush=True
                )
                if tail is not None:
                    pcm, emitted = tail
                    self._record(stats, started, emitted, pcm)
                    yield pcm
            finally:
                stats.gen_ms = (time.perf_counter() - started) * 1000.0

    @staticmethod
    def _record(stats: StreamStats, started: float, frames: int, pcm: bytes) -> None:
        if stats.ttfa_ms is None:
            stats.ttfa_ms = (time.perf_counter() - started) * 1000.0
        stats.frames = frames
        stats.pcm_bytes += len(pcm)
