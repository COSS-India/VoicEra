"""Generated token ids -> 24 kHz PCM, via SNAC's quantizer and a Vocos decoder.

Orpheus does not emit audio samples. It emits *SNAC codes* encoded as ordinary
LLM token ids, seven codes per 85.3 ms frame. This module owns that arithmetic
and the streaming decode loop.

The decoder is NOT SNAC's. ``indic-speak`` was trained against a fine-tuned
Vocos decoder that ships beside the checkpoint, and its card gives the pipeline
as ``LM -> SNAC codes -> quantizer.from_codes -> z_q [B,768,L] -> Vocos``,
stating that "Vocos replaces SNAC's decoder entirely". SNAC is still loaded,
but only 0.56 MB of it - the quantizer that turns codes into ``z_q``.

Verified model facts these rest on:

  * 7 SNAC codes = 1 frame = 2048 samples = 85.33 ms at 24 kHz
  * 1 frame = 4 SNAC latent steps of 512 samples (Vocos maps z_q[B,768,L] -> 512*L)
  * ``code = token_id - AUDIO_BASE - (index % 7) * 4096``
  * valid codes are 0..4095. Code 0 IS valid; 4096 triggers a CUDA assert
    inside SNAC, so out-of-range windows are dropped rather than decoded.
"""
from __future__ import annotations

import queue as _queue
import threading
from typing import Optional

import numpy as np

# --- Audio-code arithmetic --------------------------------------------------
AUDIO_BASE = 128266          # token id of SNAC code 0 at frame-phase 0 (<|snac_0|>)
CODES_PER_FRAME = 7
CODEBOOK_SIZE = 4096
SAMPLE_RATE = 24000
SAMPLES_PER_FRAME = 2048
FRAME_MS = SAMPLES_PER_FRAME / SAMPLE_RATE * 1000.0   # 85.333 ms
TOKENS_PER_SECOND = CODES_PER_FRAME / (FRAME_MS / 1000.0)   # 82.03 audio tokens per second

# Streaming window defaults. Vocos is non-causal, so every emitted frame needs
# real audio on both sides of it; decode wide, emit narrow, and the seam between
# consecutive emits disappears.
#
# These are measured, not derived. Decoding one frame with N frames of context
# either side and comparing it against a whole-utterance decode of the same
# codes on this checkpoint:
#
#   context   peak error vs whole-utterance decode
#   3 + 3     3.024%      audible
#   4 + 4     0.007%      inaudible
#   6 + 6     0.001%      no further gain
#
# So 4 is the knee. The analytic receptive field is wider (~21 latent frames
# from the conv stack), but influence decays long before that bound.
LEFT_CONTEXT_FRAMES = 4
RIGHT_CONTEXT_FRAMES = 4
EMIT_FRAMES = 1


def token_id_to_code(token_id: int, index: int) -> Optional[int]:
    """Map a generated token id to a SNAC code given its frame-phase ``index``.

    Returns None for non-audio tokens (text / control / wrong region). Code 0 is
    a valid audio code - do not drop it.

    BOTH bounds matter. The audio block is AUDIO_BASE .. AUDIO_BASE + 7*4096 - 1
    (128266..156937) and the Indic template's markers sit immediately above it:
    ``<|speaker>`` is 156938. Testing only ``code < 0`` accepts those four ids as
    codes 28672..28675 at every frame phase - out of range, but non-negative - so
    the caller counts them, the frame phase slips by one, and the poisoned code
    then invalidates every decode window it appears in. The model reaches for a
    turn marker at the END of an utterance, so the damage lands on the closing
    syllables. Anything at or above CODEBOOK_SIZE is not audio; reject it.
    """
    code = token_id - AUDIO_BASE - (index % CODES_PER_FRAME) * CODEBOOK_SIZE
    return None if code < 0 or code >= CODEBOOK_SIZE else code


class StreamingAudioBuffer:
    """Accumulates token ids and hands back the window to decode next.

    Rolling context: frame k is emitted from a decode of frames
    ``[k - left, k + emit + right)``, clipped to what exists. Consecutive emits
    tile the stream exactly once - no gap, no repeat - and every frame is
    decoded with the same context it would have had in a whole-utterance decode,
    which is what keeps streaming output equal to offline output.

    Windows are NOT padded to a fixed length. At the very start and the very end
    there is genuinely no audio to give, so the window is simply shorter and the
    decoder's convolutions pad the activations themselves - exactly what happens
    in an offline decode of the same utterance. Padding with code 0 instead would
    invent audio (0 is a valid code, not silence) and colour both edges.

    Decoding deliberately does not happen here: the caller dispatches windows to
    the batched decoder so the event loop is never blocked, which keeps this on
    the hot path cheap and pure.
    """

    def __init__(
        self,
        left_context: int = LEFT_CONTEXT_FRAMES,
        emit: int = EMIT_FRAMES,
        right_context: int = RIGHT_CONTEXT_FRAMES,
    ) -> None:
        self.codes: list[int] = []
        self.count = 0          # accepted audio codes so far; drives the frame phase
        self.left = left_context
        self.emit = emit
        self.right = right_context
        self.emitted = 0        # frames already handed out

    @property
    def frames(self) -> int:
        """Complete frames accumulated so far."""
        return self.count // CODES_PER_FRAME

    def push_token(self, token_id: int) -> Optional[tuple[list[int], slice]]:
        """Feed one generated token; return ``(window, emit)`` when one completes."""
        code = token_id_to_code(token_id, self.count)
        if code is None:
            return None
        self.codes.append(code)
        self.count += 1
        if self.count % CODES_PER_FRAME:
            return None
        # A frame just closed. Emit only once its right context has arrived.
        if self.frames >= self.emitted + self.emit + self.right:
            return self._window(self.emit)
        return None

    def _window(self, emit_frames: int) -> tuple[list[int], slice]:
        start = max(0, self.emitted - self.left)
        end = min(self.frames, self.emitted + emit_frames + self.right)
        window = self.codes[start * CODES_PER_FRAME:end * CODES_PER_FRAME]
        offset = self.emitted - start
        emit = slice(
            offset * SAMPLES_PER_FRAME,
            (offset + emit_frames) * SAMPLES_PER_FRAME,
        )
        self.emitted += emit_frames
        return window, emit

    def flush(self) -> list[tuple[list[int], slice]]:
        """Every frame still holding out for right context that will never come.

        Call once after generation ends. Returns [] when no complete frame was
        ever produced. Without this the tail of every utterance - where the
        closing syllable lives - is generated and then dropped.
        """
        out: list[tuple[list[int], slice]] = []
        while self.emitted < self.frames:
            out.append(self._window(min(self.emit, self.frames - self.emitted)))
        return out


class AudioDecoder:
    """SNAC's quantizer plus the checkpoint's fine-tuned Vocos decoder.

    SNAC's own decoder is never called. It was what this server used before, and
    it is the path the checkpoint's ``inference.py`` offers only as ``stock=True``
    "for A/B" - the model was trained against Vocos, so decoding with SNAC put
    every utterance off-distribution for a decoder it was not tuned for.
    """

    def __init__(
        self,
        device: str = "cuda",
        model_id: str = "hubertsiuzdak/snac_24khz",
        vocos_path: str = "",
    ) -> None:
        from snac import SNAC          # imported lazily: keeps this module importable without torch
        import torch

        self.torch = torch
        self.device = device
        self.snac = SNAC.from_pretrained(model_id).eval().to(device)
        self.vocos = self._load_vocos(vocos_path, device)
        # Decode is called from a worker thread; serialise access to the modules.
        self.lock = threading.Lock()

    @staticmethod
    def _load_vocos(vocos_path: str, device: str):
        """Build the decoder from the checkpoint's own ``vocos/load.py``.

        Loaded from the checkpoint directory rather than vendored into the image
        on purpose: ``load.py`` constructs the architecture from the weights'
        embedded config, so the two can never drift apart. It uses a relative
        import, so its parent has to be importable as a package - the same thing
        the checkpoint's own ``inference.py`` does.
        """
        import sys
        from pathlib import Path

        checkpoint = Path(vocos_path)
        if not checkpoint.is_file():
            raise FileNotFoundError(
                f"Vocos decoder not found at {checkpoint}. It ships with the checkpoint; "
                "re-run fetch.sh, or point decoder.vocos_path at it."
            )
        package_root = str(checkpoint.parent.parent)
        if package_root not in sys.path:
            sys.path.insert(0, package_root)
        from vocos.load import load_vocos

        return load_vocos(str(checkpoint), device=device)

    def decode_windows(self, windows: list[list[int]], emits: list[slice]) -> list[bytes]:
        """Decode a batch of code windows to int16 PCM.

        ``emits[i]`` selects which samples of row ``i``'s decoded window to keep.
        Windows at the head and tail of a stream are shorter than the steady-state
        ones, so rows are grouped by length and each group is decoded as its own
        batch - only equal-length rows can stack on the batch dimension.

        Rows containing an out-of-range code are returned as b"" instead of being
        decoded, so one bad row cannot take down the whole batch via the SNAC
        CUDA assert.
        """
        torch = self.torch
        results: list[bytes] = [b""] * len(windows)

        groups: dict[int, list[int]] = {}
        for i, window in enumerate(windows):
            if not window or len(window) % CODES_PER_FRAME:
                continue
            row = np.asarray(window, dtype=np.int64)
            if row.min() < 0 or row.max() >= CODEBOOK_SIZE:
                continue
            groups.setdefault(len(window), []).append(i)

        def to_gpu(a: np.ndarray):
            return torch.from_numpy(np.ascontiguousarray(a).astype(np.int32)).to(self.device)

        for length, indexes in groups.items():
            frames = length // CODES_PER_FRAME
            sub = np.asarray(
                [windows[i] for i in indexes], dtype=np.int64
            ).reshape(len(indexes), frames, CODES_PER_FRAME)
            # SNAC's hierarchy: level 0 carries 1 code per frame, level 1 carries 2,
            # level 2 carries 4. Vectorised gather beats the reference implementation's
            # per-element torch.cat loop, which costs an alloc and a sync per code.
            layers = [
                to_gpu(sub[:, :, 0]),
                to_gpu(sub[:, :, [1, 4]].reshape(len(indexes), -1)),
                to_gpu(sub[:, :, [2, 3, 5, 6]].reshape(len(indexes), -1)),
            ]
            with self.lock, torch.inference_mode():
                z_q = self.snac.quantizer.from_codes(layers)         # [B, 768, 4*frames]
                audio = self.vocos(z_q.float())                      # [B, 1, 2048*frames]
                # Scale, clamp and narrow to int16 on the GPU. Rows keep different
                # slices now, so the copy back is per row regardless - and int16 halves
                # the bytes crossing the bus versus pulling float32 and converting here.
                pcm = (audio.squeeze(1) * 32767.0).clamp_(-32768, 32767).to(torch.int16)

            host = pcm.cpu().numpy()
            for row, index in enumerate(indexes):
                results[index] = host[row][emits[index]].tobytes()
        return results


class BatchedAudioDecoder:
    """Coalesces decode requests from every concurrent stream into one GPU call.

    Steady-state windows all share a length, so they stack cleanly on a batch
    dimension: N streams cost one decode instead of N. Without this, decode
    contends with generation and streams stop being real-time well before the
    engine's admission limit is reached.

    There is no timer. The worker takes one request, drains whatever else has
    queued up behind it, and decodes that. Under load the GPU is busy long enough
    for the next batch to fill naturally; when idle, a lone request goes straight
    through.
    """

    def __init__(self, decoder: AudioDecoder, max_batch: int = 96) -> None:
        self.decoder = decoder
        self.max_batch = max_batch
        self._queue: "_queue.Queue[tuple[list[int], slice, object]]" = _queue.Queue()
        self._loop = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        import asyncio

        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="snac-decode")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    async def decode(self, window: list[int], emit: slice) -> bytes:
        future = self._loop.create_future()
        self._queue.put((window, emit, future))
        return await future

    def _worker(self) -> None:
        def settle(future, result=None, error=None):
            if future.done():
                return
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(result)

        while not self._stop.is_set():
            try:
                head = self._queue.get(timeout=0.5)
            except _queue.Empty:
                continue
            batch = [head]
            while len(batch) < self.max_batch:
                try:
                    batch.append(self._queue.get_nowait())
                except _queue.Empty:
                    break
            try:
                results = self.decoder.decode_windows(
                    [w for w, _, _ in batch], [e for _, e, _ in batch]
                )
            except Exception as exc:  # noqa: BLE001 - propagate to every waiter in the batch
                for _, _, fut in batch:
                    self._loop.call_soon_threadsafe(settle, fut, None, exc)
                continue
            for (_, _, fut), pcm in zip(batch, results):
                self._loop.call_soon_threadsafe(settle, fut, pcm, None)
