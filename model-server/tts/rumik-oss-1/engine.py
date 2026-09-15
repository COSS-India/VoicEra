"""rumik-oss-1: text -> 24 kHz PCM, streamed while it is generated.

The model emits Mimi codec tokens, eight per frame, frame-major:

    num_quantizers 8 x codebook_size 2048 = 16384 unit ids
    first_unit_id 261008 .. last_unit_id 277391      (from config.json)
    frame_rate_hz 12.5  ->  8 tokens = one frame = 80 ms = 1920 samples

So realtime is 100 tokens per second of speech, and one 3B forward pass per
token is the whole cost model.

--------------------------------------------------------------------------
Why this file exists, rather than the checkpoint's own server.py

The repo ships a working FastAPI server. It buffers: `synthesize()` generates
every token, decodes the lot through Mimi, builds a complete WAV in a BytesIO
and returns one Response. Three consequences, none of which fail loudly:

  * time-to-first-audio is the whole generation, so a 20 s utterance answers
    after 20 s of GPU work rather than after the first 160 ms of audio;
  * a client hanging up cancels nothing -- the work runs to completion behind a
    connection nobody is reading, which is exactly what the slot contract's
    "stop work when the client hangs up" row is about;
  * its request body takes `speaker`, and pydantic ignores unknown fields, so an
    OpenAI client asking for `voice="Zoya"` gets Ira with no error anywhere.

--------------------------------------------------------------------------
How tokens are streamed out of a loop with no hook

`generate_audio()` is a hand-written `for step in range(max_new_tokens)` loop.
It takes no `streamer`, exposes no callback, and uses no LogitsProcessor -- it
calls `self._constrained_sample(...)` once per token, directly.

That one call is the seam. `install_tap()` wraps it, so this file reuses their
ENTIRE loop verbatim -- sampling, the sigmoid stop head, cache handling, the
constrained vocabulary -- and only taps the token stream on its way past. The
alternative was reimplementing the loop, which means owning a copy of their
sampling semantics and having the voice change silently the day they revise it.

The same seam is the interruption point. A thread cannot be killed from
outside, so a blocking loop in a worker thread would otherwise run to the end
regardless of the client. Instead the tap raises `GenerationCancelled` on its
next call, which unwinds their loop from the inside -- GPU freed within one
token, so barge-in is real here.

Concurrency is safe because the tap is dispatched through a ContextVar rather
than an instance attribute: `asyncio.to_thread` copies the calling context, so
each stream's worker thread reads its own tap and two callers cannot be handed
each other's tokens.

--------------------------------------------------------------------------
Decoding while generating

Mimi's decoder in `transformers` has no streaming state to carry across calls
(the transformer KV could be cached; the convolution stack cannot), so frames
are decoded in a window and only the newest samples are kept:

    decode frames [total - new - RUMIK_DECODE_CONTEXT_FRAMES : total]
    emit the last  new * samples_per_frame  samples

The leading frames are context whose only job is to make the emitted samples
identical to what a single whole-clip decode would have produced. 32 frames
(2.56 s) is a generous default for a convolutional decoder with local
attention, but it is a *choice* and it is NOT yet verified on hardware -- see
the README for the check to run: stream an utterance, decode the same token
sequence in one pass, and compare sample for sample.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import threading
import time
from dataclasses import dataclass

import torch
from audio import SAMPLE_RATE
from config import Config
from prompt import PromptError, build_prompt, check_text
from transformers import AutoFeatureExtractor, AutoModelForCausalLM, AutoTokenizer, MimiModel

log = logging.getLogger("rumik.engine")

#: Pushed onto a tap when its generation has finished, one way or another. A
#: sentinel object rather than None, because None is not a token but is also not
#: obviously a terminator to a reader.
_END = object()


class GenerationCancelled(Exception):
    """Raised inside the model's own sampling loop to abandon a stream."""


class TTSGenerationError(RuntimeError):
    """Generation failed. Distinct from PromptError, which is the caller's fault."""


class _TapBase:
    """What the sampling tap needs: somewhere to put tokens, and a stop flag."""

    def __init__(self) -> None:
        self.cancelled = threading.Event()

    def push(self, item: object) -> None:
        raise NotImplementedError


class _Tap(_TapBase):
    """One request's window into the model's sampling loop.

    Lives in the request's context and is written from the worker thread. The
    queue is an asyncio queue fed through `call_soon_threadsafe`, so the
    consumer never polls and the event loop is never blocked on a token.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._loop = loop
        self._queue: asyncio.Queue = asyncio.Queue()

    def push(self, item: object) -> None:
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, item)
        except RuntimeError:
            # The loop is already closed -- the caller is long gone and there is
            # nobody to hand this token to. Dropping it is correct; raising here
            # would surface inside the model's loop as a generation failure.
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
    """Wrap the model's per-token sampling call. Idempotent.

    Assigns to the instance, so `self._constrained_sample` inside their loop
    finds this while the class method stays untouched.
    """
    if getattr(model, "_rumik_tapped", False):
        return
    if not hasattr(model, "_constrained_sample"):
        raise TTSGenerationError(
            "this checkpoint's model class has no _constrained_sample, which is the "
            "per-token seam this server streams and cancels through. The upstream "
            "generation loop has changed shape; re-read modeling_rumik_oss.py before "
            "deploying it."
        )
    original = model._constrained_sample

    def tapped(*args, **kwargs):
        tap = _TAP.get()
        if tap is not None and tap.cancelled.is_set():
            # Unwinds their loop from the inside. The only way to stop a
            # blocking generation from outside its own thread.
            raise GenerationCancelled
        token = original(*args, **kwargs)
        if tap is not None:
            tap.push(int(torch.as_tensor(token).reshape(-1)[0].item()))
        return token

    model._constrained_sample = tapped
    model._rumik_tapped = True


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


class RumikTTSEngine:
    """Loads the checkpoint and turns requests into streamed PCM."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.model = None
        self.tokenizer = None
        self.mimi = None
        self.speakers: tuple[str, ...] = ()
        self.sample_rate = SAMPLE_RATE
        self.samples_per_frame = 1920
        self.frame_ms = 80.0
        self.quantizers = 8
        self.max_position_embeddings = 8192
        self._slots = asyncio.Semaphore(cfg.max_concurrency)

    # ---------------------------------------------------------------- loading
    def load(self) -> None:
        """Blocking. Call it off the event loop, so /health can answer 'loading'."""
        cfg = self.cfg
        dtype = getattr(torch, cfg.dtype, None)
        if not isinstance(dtype, torch.dtype):
            raise TTSGenerationError(f"RUMIK_DTYPE={cfg.dtype!r} is not a torch dtype")

        log.info("loading %s on %s (%s)", cfg.model_path, cfg.device, cfg.dtype)
        self.tokenizer = AutoTokenizer.from_pretrained(cfg.model_path, trust_remote_code=True)
        self.model = (
            AutoModelForCausalLM.from_pretrained(
                cfg.model_path,
                trust_remote_code=True,
                dtype=dtype,
                attn_implementation=cfg.attn_implementation,
            )
            .eval()
            .to(cfg.device)
        )
        self.mimi = (
            MimiModel.from_pretrained(f"{cfg.model_path}/codec", dtype=dtype)
            .eval()
            .to(cfg.decoder_device)
        )

        conf = self.model.config
        self.quantizers = int(getattr(conf, "num_quantizers", 8))
        self.max_position_embeddings = int(getattr(conf, "max_position_embeddings", 8192))
        self.speakers = tuple(getattr(conf, "speakers", ()) or ())
        if not self.speakers:
            raise TTSGenerationError(
                "config.json declares no `speakers`. The voice roster is read from the "
                "checkpoint rather than hardcoded, so there is nothing to offer callers."
            )

        # The codec states its own rate; trust it over the constant and fail if
        # they disagree, because the constant is what audio.py writes into WAV
        # headers and what clients are told in X-Sample-Rate.
        rate = int(AutoFeatureExtractor.from_pretrained(f"{cfg.model_path}/codec").sampling_rate)
        if rate != SAMPLE_RATE:
            raise TTSGenerationError(
                f"the codec reports {rate} Hz but this folder is built around "
                f"{SAMPLE_RATE} Hz (audio.py, the WAV headers and X-Sample-Rate). "
                f"A codec revision changed the rate; update audio.SAMPLE_RATE."
            )
        self.sample_rate = rate

        # Measured, not assumed: decode a known number of all-zero frames (0 is a
        # valid Mimi code) and see how many samples come back. This number is what
        # the window slicing depends on, so deriving it from the decoder itself
        # means a codec with different strides cannot silently shift the audio.
        probe_frames = 8
        probe = torch.zeros(1, self.quantizers, probe_frames, dtype=torch.long)
        with torch.inference_mode():
            out = self.mimi.decode(probe.to(self.mimi.device)).audio_values
        self.samples_per_frame = int(out.shape[-1]) // probe_frames
        self.frame_ms = self.samples_per_frame / self.sample_rate * 1000.0
        log.info(
            "codec: %d quantizers, %d samples/frame (%.1f ms), %d Hz",
            self.quantizers, self.samples_per_frame, self.frame_ms, self.sample_rate,
        )

        install_tap(self.model)
        if cfg.warmup_enabled:
            self._warmup()

    def _warmup(self) -> None:
        """One short synthesis, to pay the JIT and autotune costs before traffic.

        It also proves the tap works: if `_constrained_sample` ever stops being
        the per-token seam, this raises at startup rather than serving a stream
        that produces no tokens and looks like a wedged GPU.
        """
        tap = _ListTap()
        holder = _TAP.set(tap)
        try:
            started = time.perf_counter()
            self._generate_blocking(
                prompt=build_prompt(voice=self.speakers[0], instructions="", text="नमस्ते"),
                max_new_tokens=max(self.quantizers, self.cfg.warmup_tokens),
                temperature=self.cfg.temperature,
                top_k=self.cfg.top_k,
            )
            elapsed = (time.perf_counter() - started) * 1000.0
        finally:
            _TAP.reset(holder)

        if not tap.tokens:
            raise TTSGenerationError(
                "warmup generated no tokens through the sampling tap. The upstream "
                "generation loop no longer routes every token through "
                "_constrained_sample, so streaming and cancellation are both broken. "
                "See install_tap()."
            )
        log.info("warmup: %d tokens in %.0f ms (%.1f tok/s)",
                 len(tap.tokens), elapsed, len(tap.tokens) / (elapsed / 1000.0))

    # ------------------------------------------------------------- generation
    def _generate_blocking(self, *, prompt: str, max_new_tokens: int,
                           temperature: float, top_k: int) -> None:
        """Run their loop. The result is discarded: the tap already has the tokens."""
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        with torch.inference_mode():
            self.model.generate_audio(
                **inputs,
                max_new_tokens=max_new_tokens,
                min_new_tokens=self.cfg.min_new_tokens,
                temperature=temperature,
                top_k=top_k,
                do_sample=True,
            )

    def _decode_new_frames(self, tokens: list[int], emitted: int,
                           *, flush: bool) -> tuple[bytes, int] | None:
        """PCM for whatever complete frames have appeared since `emitted`.

        De-interleaving is delegated to the model's own `audio_tokens_to_codes`,
        which owns the round-robin resync rule (a token whose quantizer index is
        not the next one expected discards the partial frame). Reimplementing
        that here would be a second copy of the rule that decides whether the
        output is speech or noise.
        """
        codes = self.model.audio_tokens_to_codes(tokens)
        # An empty result is shaped (1, 0) rather than (1, Q, 0): their builder
        # transposes a list of frames, and transposing [] loses the rank.
        if codes.ndim != 3 or codes.shape[-1] == 0:
            return None
        total = int(codes.shape[-1])
        new = total - emitted
        if new <= 0 or (not flush and new < self.cfg.decode_chunk_frames):
            return None

        start = max(0, total - new - self.cfg.decode_context_frames)
        window = codes[:, :, start:total].to(self.mimi.device)
        with torch.inference_mode():
            wav = self.mimi.decode(window).audio_values[0, 0]
        keep = new * self.samples_per_frame
        fresh = wav[-keep:] if int(wav.shape[-1]) > keep else wav

        arr = fresh.float().cpu().clamp(-1.0, 1.0).numpy()
        return (arr * 32767.0).astype("<i2").tobytes(), total

    # ------------------------------------------------------------- the stream
    def plan(self, *, text: str, voice: str | None,
             instructions: str | None, max_new_tokens: int | None) -> tuple[str, int]:
        """Validate the request and return (prompt, token budget).

        Separate from the generator so everything a caller can fix -- unknown
        voice, empty or over-long input, no room left in the context window --
        raises before the first byte and becomes a 400. Once a StreamingResponse
        has sent its status line the only way left to signal failure is to stop
        writing audio.
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
            voice=chosen,
            instructions=described,
            text=check_text(text, cfg.max_input_chars),
        )

        prompt_len = int(self.tokenizer(prompt, return_tensors="pt")["input_ids"].shape[-1])
        # Audio tokens share the context window with the prompt, so a long
        # description shortens the utterance. Clamped here rather than left to
        # fail deep inside the loop as a position-embedding error.
        budget = self.max_position_embeddings - prompt_len
        if budget <= cfg.min_new_tokens:
            raise PromptError(
                f"the prompt uses {prompt_len} of {self.max_position_embeddings} context "
                f"positions, leaving no room for audio. Shorten `input` or `instructions`."
            )
        cap = min(max_new_tokens or cfg.max_new_tokens_default, cfg.max_new_tokens_limit, budget)
        return prompt, cap

    async def synthesize_stream(self, *, prompt: str, max_new_tokens: int,
                                temperature: float | None, top_k: int | None,
                                stats: StreamStats):
        """Yield 24 kHz mono s16le PCM as it is generated.

        Take `prompt` and `max_new_tokens` from :meth:`plan`, which is where a
        bad request is refused.
        """
        cfg = self.cfg
        stats.frame_ms = self.frame_ms
        tap = _Tap(asyncio.get_running_loop())
        holder = _TAP.set(tap)
        try:
            async with self._slots:
                worker = asyncio.create_task(
                    self._drive(tap, prompt, max_new_tokens,
                                temperature if temperature is not None else cfg.temperature,
                                top_k if top_k is not None else cfg.top_k)
                )
                # On the barge-in path nobody awaits this task, and asyncio
                # reports an unretrieved exception as though the event loop
                # itself were at fault. Retrieved here; reported below.
                worker.add_done_callback(_retrieve)

                tokens: list[int] = []
                emitted = 0
                started = time.perf_counter()
                try:
                    while True:
                        item = await tap.get()
                        if item is _END:
                            break
                        tokens.append(int(item))  # type: ignore[arg-type]
                        stats.tokens = len(tokens)
                        # Cheap gate: de-interleaving can drop tokens, so this
                        # only decides when it is worth asking.
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

                    # _END is pushed from the worker's `finally`, so the task can
                    # still be a moment from done when the loop above exits.
                    # Awaiting it is what turns a failed generation into an error
                    # instead of a stream that just stopped early.
                    await worker
                finally:
                    stats.gen_ms = (time.perf_counter() - started) * 1000.0
                    # Barge-in, an error, or a clean finish: setting this is
                    # harmless once generation is over, and is the only thing
                    # that stops it when it is not.
                    tap.cancelled.set()
        finally:
            _TAP.reset(holder)

    @staticmethod
    def _record(stats: StreamStats, started: float, frames: int, pcm: bytes) -> None:
        if stats.ttfa_ms is None:
            stats.ttfa_ms = (time.perf_counter() - started) * 1000.0
        stats.frames = frames
        stats.pcm_bytes += len(pcm)

    async def _drive(self, tap: _Tap, prompt: str, max_new_tokens: int,
                     temperature: float, top_k: int) -> None:
        try:
            await asyncio.to_thread(
                self._generate_blocking, prompt=prompt, max_new_tokens=max_new_tokens,
                temperature=temperature, top_k=top_k,
            )
        except GenerationCancelled:
            log.info("generation cancelled by the caller")
        finally:
            tap.push(_END)


def _retrieve(task: asyncio.Task) -> None:
    """Mark a worker's exception as seen. Reporting happens at the await."""
    if not task.cancelled():
        task.exception()
