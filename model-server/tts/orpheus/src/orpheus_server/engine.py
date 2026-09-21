"""The synthesis engine: one vLLM engine plus one shared batched SNAC decoder.

Everything latency-sensitive lives here. Two design points worth knowing before
changing anything:

  * vLLM hands back a *cumulative* token list on every streaming step, and that
    list keeps growing while we await a decode. The loop below snapshots it and
    tracks a cursor over the snapshot; reading the live list instead silently
    drops tokens (audible as clipped syllables).
  * Per-request timings live on a ``StreamStats`` object owned by the caller, not
    in a process-global. With concurrent streams a global ``last_ttfa`` reports
    whichever request happened to finish last, which is how you end up publishing
    another stream's latency in your own response headers.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Optional

from . import codec, prompt
from .config import Settings
from .voices import Roster

log = logging.getLogger("orpheus.engine")


@dataclass
class StreamStats:
    """Timings for one synthesis request. Owned by the caller; never shared."""

    ttfa_ms: Optional[float] = None      # time to first audio chunk
    tokens: int = 0                      # audio tokens generated
    frames: int = 0                      # 85.33 ms frames emitted
    pcm_bytes: int = 0
    gen_ms: float = 0.0
    gaps_ms: list[float] = field(default_factory=list)
    finish_reason: Optional[str] = None  # end_of_speech | text_eos | max_tokens
    soft_eos_ignored: int = 0            # spurious text-eos tokens generated through

    @property
    def audio_ms(self) -> float:
        return self.frames * codec.FRAME_MS

    @property
    def rtf(self) -> Optional[float]:
        """Generation time / audio duration. Below 1.0 is faster than real time."""
        return round(self.gen_ms / self.audio_ms, 3) if self.audio_ms else None

    @property
    def tokens_per_s(self) -> Optional[float]:
        return round(self.tokens / (self.gen_ms / 1000.0), 1) if self.gen_ms else None

    def summary(self) -> dict:
        return {
            "ttfa_ms": round(self.ttfa_ms, 1) if self.ttfa_ms is not None else None,
            "audio_ms": round(self.audio_ms, 1),
            "gen_ms": round(self.gen_ms, 1),
            "rtf": self.rtf,
            "tokens": self.tokens,
            "tokens_per_s": self.tokens_per_s,
            "frames": self.frames,
            "finish_reason": self.finish_reason,
            "soft_eos_ignored": self.soft_eos_ignored,
        }


@dataclass
class Metrics:
    """Process-wide counters. Deliberately aggregate only - see StreamStats."""

    requests_total: int = 0
    streams_active: int = 0
    errors_total: int = 0
    audio_seconds_total: float = 0.0

    def snapshot(self) -> dict:
        return {
            "requests_total": self.requests_total,
            "streams_active": self.streams_active,
            "errors_total": self.errors_total,
            "audio_seconds_total": round(self.audio_seconds_total, 2),
        }


class TTSEngine:
    def __init__(self, settings: Settings, roster: Roster) -> None:
        self.settings = settings
        self.roster = roster
        self.metrics = Metrics()
        self.model_path = settings.resolved_model_path()
        self.started_at: Optional[float] = None
        self._engine = None
        self._tokenizer = None
        self._stop: prompt.StopTokens = prompt.resolve_stop_tokens(None)
        self._decoder: Optional[codec.AudioDecoder] = None
        self._batcher: Optional[codec.BatchedAudioDecoder] = None
        self._ready = asyncio.Event()

    # -- lifecycle ----------------------------------------------------------
    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    async def start(self) -> None:
        from transformers import AutoTokenizer
        from vllm import AsyncEngineArgs, AsyncLLMEngine

        cfg = self.settings
        # Empty vocos_path means "beside the checkpoint", which is where fetch.sh
        # puts it. Resolved here rather than in the config default because it
        # depends on the model path.
        vocos_path = cfg.decoder.vocos_path or str(Path(self.model_path) / "vocos" / "best.pt")
        log.info(
            "loading codec: SNAC quantizer %s + Vocos decoder %s on %s",
            cfg.decoder.model_id, vocos_path, cfg.decoder.device,
        )
        self._decoder = codec.AudioDecoder(
            device=cfg.decoder.device,
            model_id=cfg.decoder.model_id,
            vocos_path=vocos_path,
        )
        self._batcher = codec.BatchedAudioDecoder(self._decoder, max_batch=cfg.decoder.max_batch)
        self._batcher.start()
        log.info(
            "streaming window: %d left + %d emit + %d right frames",
            cfg.decoder.left_context_frames, cfg.decoder.emit_frames,
            cfg.decoder.right_context_frames,
        )

        log.info(
            "loading model %s (dtype=%s quantization=%s max_num_seqs=%d gpu_mem=%.2f tp=%d)",
            self.model_path, cfg.model.dtype, cfg.model.quantization,
            cfg.engine.max_num_seqs, cfg.engine.gpu_memory_utilization,
            cfg.engine.tensor_parallel_size,
        )
        args = AsyncEngineArgs(
            model=self.model_path,
            dtype=cfg.model.dtype,
            quantization=cfg.model.quantization,
            max_model_len=cfg.model.max_model_len,
            trust_remote_code=cfg.model.trust_remote_code,
            gpu_memory_utilization=cfg.engine.gpu_memory_utilization,
            max_num_seqs=cfg.engine.max_num_seqs,
            enforce_eager=cfg.engine.enforce_eager,
            tensor_parallel_size=cfg.engine.tensor_parallel_size,
            disable_log_stats=True,
        )
        self._engine = AsyncLLMEngine.from_engine_args(args)
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        self._stop = prompt.resolve_stop_tokens(self._tokenizer)
        log.info(
            "stop tokens: hard=%s (end of speech) soft=%s (backbone text eos, judged against "
            "the text when engine.soft_text_eos is on)",
            list(self._stop.hard), list(self._stop.soft),
        )

        if cfg.warmup.enabled:
            await self._warmup()
        self.started_at = time.time()
        self._ready.set()
        log.info("ready: serving %s", cfg.server.model_name)

    async def _drain(self, timeout: float) -> None:
        """Let in-flight streams finish before the engine is torn down.

        Without this, a restart cuts every live stream mid-sentence. Note the
        container's ``stop_grace_period`` has to exceed this, or Docker sends
        SIGKILL while the drain is still waiting.
        """
        if timeout <= 0 or self.metrics.streams_active <= 0:
            return
        log.info("draining %d in-flight stream(s), up to %.0fs",
                 self.metrics.streams_active, timeout)
        deadline = time.monotonic() + timeout
        while self.metrics.streams_active > 0 and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        if self.metrics.streams_active > 0:
            log.warning("drain timed out with %d stream(s) still active; cutting them off",
                        self.metrics.streams_active)
        else:
            log.info("drain complete")

    async def stop(self) -> None:
        # Unready first: new requests get 503 from the dependency while streams
        # already in flight are given time to finish their sentence.
        self._ready.clear()
        await self._drain(self.settings.server.drain_timeout)
        if self._batcher is not None:
            self._batcher.stop()
        if self._engine is not None:
            # vLLM has moved this method between releases. Call whichever name is
            # present rather than suppressing the AttributeError: a silent no-op
            # here leaves the engine subprocess holding VRAM, and the next boot
            # fails with an out-of-memory error that points nowhere near the cause.
            shutdown = getattr(self._engine, "shutdown", None) or getattr(
                self._engine, "shutdown_background_loop", None
            )
            if shutdown is None:
                log.warning(
                    "this vLLM build exposes neither shutdown() nor shutdown_background_loop(); "
                    "GPU memory may not be released until the process exits"
                )
            else:
                try:
                    shutdown()
                except Exception:
                    log.exception("vLLM engine shutdown failed")
        self._engine = None

    async def _warmup(self) -> None:
        """Pre-compile Triton kernels for each batch width we expect to serve.

        vLLM's sampling kernels JIT-compile per batch shape on first use. Without
        this, the first burst of N concurrent users pays a multi-second stall
        mid-stream; paying it here costs boot time nobody is waiting on.
        """
        language = self.roster.languages[0]
        voice = language["voices"][0]
        text = self.roster.sample_text(language["code"])

        async def once() -> None:
            stats = StreamStats()
            async for _ in self.stream_pcm(
                text=text, voice=voice, language=language["code"],
                style=self.roster.default_style,
                max_tokens=self.settings.warmup.max_tokens, stats=stats,
            ):
                pass

        widths = [w for w in sorted(set(self.settings.warmup.concurrency_widths)) if w >= 1]
        failures = 0
        for width in widths:
            log.info("warmup: concurrency %d", width)
            try:
                await asyncio.gather(*[once() for _ in range(width)])
            except Exception:
                # Keep booting - one width failing is not worth refusing to serve -
                # but never silently. Warmup is the first end-to-end exercise of the
                # checkpoint, so it is where a bad one shows up first.
                failures += 1
                log.exception("warmup failed at concurrency %d; continuing", width)
        if widths and failures == len(widths):
            log.error(
                "every warmup width failed: the server will report ready, but synthesis is "
                "almost certainly broken. A tokenizer.json that does not match the checkpoint "
                "is the usual cause - see docs/MODEL_SETUP.md."
            )

    # -- synthesis ----------------------------------------------------------
    def clamp_max_tokens(self, requested: Optional[int], text: Optional[str] = None) -> int:
        """The generation cap for one request.

        An explicit ``max_tokens`` is honoured as given (clamped to the ceiling):
        a caller that names a number has said what it wants. When the request
        omits one, ``max_tokens_default`` is 8192 - about 100 seconds - and the
        only thing that ends an utterance before that is the model emitting the
        end-of-speech token. Sampling misses it often enough to matter, and every
        token generated afterwards is decoded and streamed as audio, which is
        heard as babble on the end of a short clip.

        So when ``text`` is known and the guard is on, the cap is sized from the
        text instead. Deliberately loose - it is a runaway bound, not a length
        estimate, and truncating real speech would be a worse bug than the one it
        prevents.
        """
        cfg = self.settings.engine
        if requested is not None:
            return max(64, min(int(requested), cfg.max_tokens_limit))

        value = cfg.max_tokens_default
        if cfg.duration_guard and text and text.strip():
            budget = int(self._expected_audio_tokens(text) * cfg.guard_headroom)
            value = min(value, max(cfg.guard_floor_tokens, budget))
        return max(64, min(value, cfg.max_tokens_limit))

    def _expected_audio_tokens(self, text: Optional[str]) -> int:
        """Audio tokens this text should take to read, before any headroom.

        One estimate, used twice and deliberately not duplicated: multiplied by
        ``guard_headroom`` it is the runaway cap above, and multiplied by
        ``soft_text_eos_min_fraction`` it is the floor below which a backbone text
        eos is not believed. Returns 0 when there is no text to reason from, which
        callers read as "no opinion".
        """
        cfg = self.settings.engine
        if not text or not text.strip():
            return 0
        seconds = len(text.strip()) / cfg.guard_chars_per_second
        return int(seconds * codec.TOKENS_PER_SECOND)

    def _text_eos_is_final(self, generated: int, expected: int) -> bool:
        """Whether a backbone text eos should be taken as the end of the utterance.

        See :class:`prompt.StopTokens`: the checkpoint hands this id to its own
        ``generate`` as both ``eos_token_id`` and ``pad_token_id``, so its presence
        proves nothing on its own. It is believed only once enough audio exists for
        the text that was actually asked for. With no text to reason from, or with
        the judgement disabled, it is obeyed as before.
        """
        cfg = self.settings.engine
        if not cfg.soft_text_eos or expected <= 0:
            return True
        return generated >= expected * cfg.soft_text_eos_min_fraction

    async def _abort(self, request_id: str) -> None:
        """Stop a generation we have decided to end early.

        Without this the engine goes on decoding tokens nobody will ever hear and
        holds a sequence slot for the rest of its budget - which matters here
        because nothing else in this server aborts anything.
        """
        abort = getattr(self._engine, "abort", None)
        if abort is None:
            return
        try:
            result = abort(request_id)
            if inspect.isawaitable(result):
                await result
        except Exception:                                        # noqa: BLE001
            log.debug("abort(%s) failed; request will finish on its own",
                      request_id, exc_info=True)

    def preflight(self, text: str, voice: str, style: Optional[str]) -> list[int]:
        """Validate a request while an HTTP status code can still be returned.

        A streaming response commits its status line and headers before the first
        audio byte, so a failure discovered later can only truncate the body - the
        client sees ``200 OK`` and short or empty audio. Everything knowable up
        front is therefore checked here, in the request handler, before any
        response object is constructed.

        Returns the prompt token ids so the stream does not build them twice.
        Raises ``ValueError`` with a message meant for the client.
        """
        if self._tokenizer is None:
            raise RuntimeError("engine is not loaded")
        if not text or not text.strip():
            raise ValueError("input text is empty")
        token_ids = prompt.build_prompt_token_ids(
            self._tokenizer, self.roster.template, text, voice, style
        )
        limit = self.settings.model.max_model_len
        if len(token_ids) >= limit:
            raise ValueError(
                f"input is too long: {len(token_ids)} prompt tokens against a max_model_len "
                f"of {limit}. Split the text into shorter requests."
            )
        return token_ids

    async def stream_pcm(
        self,
        text: str,
        voice: str,
        language: str,
        style: Optional[str],
        max_tokens: int,
        stats: StreamStats,
        token_ids: Optional[list[int]] = None,
    ) -> AsyncIterator[bytes]:
        """Yield 24 kHz mono s16le PCM, one 85.33 ms frame at a time.

        ``stats`` is filled in as the stream progresses so the caller can report
        this request's own latency rather than a shared global's.

        ``token_ids`` is the prompt already built by :meth:`preflight`. Callers
        that skip preflight (warmup) leave it None and it is built here.
        """
        from vllm import SamplingParams, TokensPrompt

        if self._engine is None:
            raise RuntimeError("engine is not loaded")
        if not text or not text.strip():
            raise ValueError("input text is empty")

        sampling = self.settings.sampling
        if token_ids is None:
            token_ids = prompt.build_prompt_token_ids(
                self._tokenizer, self.roster.template, text, voice, style
            )
        params = SamplingParams(
            temperature=sampling.temperature,
            top_p=sampling.top_p,
            top_k=sampling.top_k,
            repetition_penalty=sampling.repetition_penalty,
            max_tokens=max_tokens,
            min_tokens=sampling.min_tokens,
            # Only the token that actually closes the audio span is an
            # unconditional stop. The backbone's text eos is handled below,
            # where the text is available to judge it against.
            stop_token_ids=list(self._stop.hard),
            detokenize=False,          # we never want text back; skip the detokenizer entirely
        )

        decoder_cfg = self.settings.decoder
        buffer = codec.StreamingAudioBuffer(
            left_context=decoder_cfg.left_context_frames,
            emit=decoder_cfg.emit_frames,
            right_context=decoder_cfg.right_context_frames,
        )
        cursor = 0
        started = time.perf_counter()
        last_chunk_at: Optional[float] = None
        bytes_per_frame = codec.SAMPLES_PER_FRAME * 2

        def account(pcm: bytes) -> None:
            """Record one emitted chunk. Head and tail chunks carry two frames."""
            nonlocal last_chunk_at
            now = time.perf_counter()
            if stats.ttfa_ms is None:
                stats.ttfa_ms = (now - started) * 1000.0
            elif last_chunk_at is not None:
                stats.gaps_ms.append((now - last_chunk_at) * 1000.0)
            last_chunk_at = now
            stats.frames += len(pcm) // bytes_per_frame
            stats.pcm_bytes += len(pcm)

        request_id = str(uuid.uuid4())
        generator = self._engine.generate(
            TokensPrompt(prompt_token_ids=token_ids), params, request_id
        )
        soft_stop = set(self._stop.soft)
        expected = self._expected_audio_tokens(text)
        ended_on_text_eos = False
        vllm_finish: Optional[str] = None

        async for output in generator:
            # Snapshot: this list keeps growing while we await the decode below.
            completion = output.outputs[0]
            tokens = list(completion.token_ids)
            vllm_finish = completion.finish_reason
            for token_id in tokens[cursor:]:
                if token_id in soft_stop:
                    if self._text_eos_is_final(stats.tokens, expected):
                        stats.finish_reason = "text_eos"
                        ended_on_text_eos = True
                        break
                    # Ambiguous by construction - the checkpoint uses this same id
                    # as its pad token - and far too little audio exists for it to
                    # be the end of this text. Drop it and keep generating.
                    stats.soft_eos_ignored += 1
                    continue
                stats.tokens += 1
                pending = buffer.push_token(token_id)
                if pending is None:
                    continue
                pcm = await self._batcher.decode(*pending)
                if not pcm:
                    continue
                account(pcm)
                yield pcm
            cursor = len(tokens)
            if ended_on_text_eos:
                break

        if ended_on_text_eos:
            await self._abort(request_id)
        elif stats.finish_reason is None:
            # vLLM's own word for why it stopped, mapped to what it means here.
            stats.finish_reason = {
                "stop": "end_of_speech", "length": "max_tokens",
            }.get(vllm_finish or "", vllm_finish)
        if stats.soft_eos_ignored:
            log.debug("ignored %d spurious text-eos token(s) before %s (%d tokens, expected ~%d)",
                      stats.soft_eos_ignored, stats.finish_reason, stats.tokens, expected)

        # The trailing frames still waiting on right context that will never
        # arrive. Without this the closing syllable of every utterance is
        # generated and then thrown away.
        for window, emit in buffer.flush():
            pcm = await self._batcher.decode(window, emit)
            if pcm:
                account(pcm)
                yield pcm

        stats.gen_ms = (time.perf_counter() - started) * 1000.0
        self.metrics.audio_seconds_total += stats.audio_ms / 1000.0
