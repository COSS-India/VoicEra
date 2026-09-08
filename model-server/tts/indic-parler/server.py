"""Indic Parler TTS — OpenAI-compatible speech endpoint.

POST /v1/audio/speech streams raw PCM as it is generated. The engine underneath
is unchanged: one worker thread owns the runner, prefills arriving requests and
steps the whole batch together (continuous batching).

Barge-in: when a caller is interrupted, Pipecat cancels the task reading this
response, which closes the connection. The generator's `finally` then queues the
request id for eviction, and the worker frees its KV slot on the next tick. The
previous WebSocket transport did not do this -- it stopped sending audio but let
the generation run to completion, holding one of the runner's slots the whole
time.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import queue
import threading
import traceback
import uuid
from typing import Literal

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from inference.runner import ParlerTTSModelRunner, TTSRequest
from pydantic import BaseModel, Field

# Parler's DAC vocoder runs at 44.1 kHz mono.
AUDIO_SAMPLE_RATE = 44100

app = FastAPI(title="Indic Parler TTS")

_runner: ParlerTTSModelRunner | None = None
_prefill_q: queue.Queue = queue.Queue()
_cancel_q: queue.Queue = queue.Queue()
_stop_evt = threading.Event()
#: Set when the inference worker dies. Until this existed a dead worker was
#: indistinguishable from a slow one: every caller blocked on out_q.get()
#: forever, /health still answered 200, and `restart: unless-stopped` never
#: fired because the process was still alive.
_worker_error: str | None = None


# ---------------------------------------------------------------- request

class SpeechRequest(BaseModel):
    """OpenAI /v1/audio/speech, plus the fields Parler needs.

    `voice` is the speaker preset and `instructions` the free-text style prompt;
    they are joined exactly as the previous client did before sending, so the
    model receives an identical description.
    """

    # Bounded because the engine is not: the description is T5-encoded into
    # the cross-attention KV cache, which is a fixed 384 slots wide. An
    # over-long value raised inside prefill, and a raise inside prefill used
    # to take the whole slot down. A 422 here is the same rejection, before
    # anything touches the GPU. These are guard rails, not tuned limits.
    input: str = Field(min_length=1, max_length=2000)
    model: str | None = None
    voice: str | None = Field(default=None, max_length=200)
    instructions: str = Field(
        default="A clear, natural voice with good audio quality.", max_length=1000
    )
    # pcm_f32le is the engine's native output. `pcm` converts to 16-bit.
    response_format: Literal["pcm_f32le", "pcm"] = "pcm_f32le"
    language: str = "hi"
    speed: float = Field(default=1.0, description="Accepted for compatibility; not applied.")

    def description(self) -> str:
        return f"{self.voice}. {self.instructions}" if self.voice else self.instructions


# ---------------------------------------------------------------- worker

def inference_worker(runner: ParlerTTSModelRunner, decode_every: int) -> None:
    """Run the batch loop, and make its death visible if it dies.

    Nothing here is expected to raise. But an unhandled exception used to end
    the thread silently, and the failure had no symptom anywhere: callers hung
    on a queue nobody would ever put to, /health kept answering `healthy`, and
    Docker saw a running process. Reaching a dead worker had to be indefinite
    waiting rather than an error, which is the opposite of what this stack is
    careful about everywhere else.
    """
    global _worker_error
    pending_out: dict[str, queue.Queue] = {}
    try:
        _worker_loop(runner, decode_every, pending_out)
    except Exception as exc:                                        # noqa: BLE001
        _worker_error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        # Fail everyone still waiting, rather than leaving them blocked.
        for q_out in pending_out.values():
            q_out.put(("error", f"inference worker died: {_worker_error}"))
        pending_out.clear()


@torch.no_grad()
def _worker_loop(
    runner: ParlerTTSModelRunner, decode_every: int, pending_out: dict[str, queue.Queue]
) -> None:
    """Drain new requests (prefill), drop cancelled ones, then step the batch."""
    step_count = 0

    while not _stop_evt.is_set():
        # New work.
        while True:
            try:
                job = _prefill_q.get_nowait()
            except queue.Empty:
                break
            if job is None:
                return
            req, out_q = job
            pending_out[req.pid] = out_q
            try:
                runner.prefill(req)
            except Exception as exc:                                # noqa: BLE001
                # prefill registers the request before the work that can
                # fail. Reporting the error without undoing that left a
                # running_requests entry with no KV slot behind it, and the
                # next step() raised KeyError in _ordered_pids -- killing
                # this thread and hanging every other caller on the box.
                runner.abort_prefill(req.pid)
                out_q.put(("error", str(exc)))
                pending_out.pop(req.pid, None)

        # Abandoned work. Freeing the slot is the whole point of barge-in.
        while True:
            try:
                pid = _cancel_q.get_nowait()
            except queue.Empty:
                break
            req = runner.running_requests.get(pid)
            if req is not None:
                runner.evict(req)
                # Nobody is listening, so skip the final DAC decode evict queued.
                runner._pending_final_tokens.pop(pid, None)
            pending_out.pop(pid, None)

        if runner.running_requests:
            before = set(runner.running_requests.keys())
            runner.step()
            runner.check_stopping_criteria()
            finished = before - set(runner.running_requests.keys())
            step_count += 1

            should_decode = bool(finished) or (step_count % decode_every == 0)
            for pid, arr in (runner.audio_decode() if should_decode else {}).items():
                q_out = pending_out.get(pid)
                if q_out is not None:
                    q_out.put(("audio", arr))

            for pid in finished:
                q_out = pending_out.pop(pid, None)
                if q_out is not None:
                    q_out.put(("done", None))
        else:
            _stop_evt.wait(0.005)


# ---------------------------------------------------------------- routes

@app.get("/health")
def health():
    """503 until the model is loaded, and again if the worker has died.

    The slot contract is 2xx *once the model is loaded and can serve*. This
    used to answer 200 while still loading and 200 after the worker died, so
    a container healthcheck could never tell either state from a healthy one.
    """
    body = {
        "status": "healthy",
        "sample_rate": AUDIO_SAMPLE_RATE,
        "running_requests": len(_runner.running_requests) if _runner else 0,
        "worker_error": _worker_error,
    }
    if _worker_error is not None:
        body["status"] = "worker_dead"
        return JSONResponse(status_code=503, content=body)
    if _runner is None:
        body["status"] = "loading"
        return JSONResponse(status_code=503, content=body)
    return body


@app.post("/v1/audio/speech")
async def speech(req: SpeechRequest):
    out_q: queue.Queue = queue.Queue()
    pid = uuid.uuid4().hex[:8]
    _prefill_q.put((TTSRequest(prompt=req.input, description=req.description(), pid=pid), out_q))

    to_int16 = req.response_format == "pcm"

    async def stream():
        completed = False
        try:
            while True:
                # Bounded get. An unbounded one parked a default-executor
                # thread for the life of the process on every barge-in: the
                # future is cancelled but the thread is already inside
                # queue.get(), and the cancel handler below drops the queue
                # so nothing is ever put to it. The executor caps at
                # min(32, cpu+4), so ~32 barge-ins stalled every to_thread
                # in the process, healthy requests included.
                try:
                    kind, payload = await asyncio.to_thread(out_q.get, True, 0.25)
                except queue.Empty:
                    continue
                if kind == "error":
                    # Headers are already sent; ending the body is the only signal left.
                    return
                if kind == "audio":
                    arr = payload.astype(np.float32)
                    if to_int16:
                        yield (np.clip(arr, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
                    else:
                        yield arr.tobytes()
                elif kind == "done":
                    completed = True
                    return
        finally:
            # Client vanished mid-generation -- free the GPU slot.
            if not completed:
                _cancel_q.put(pid)

    return StreamingResponse(
        stream(),
        media_type="audio/pcm",
        headers={
            "X-Sample-Rate": str(AUDIO_SAMPLE_RATE),
            "X-Audio-Format": req.response_format,
            "X-Channels": "1",
            "Cache-Control": "no-store",
        },
    )


# ---------------------------------------------------------------- startup

def main() -> None:
    parser = argparse.ArgumentParser(description="Indic Parler TTS (OpenAI-compatible)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8002)
    here = os.path.dirname(os.path.abspath(__file__))
    parser.add_argument("--checkpoint", default=os.path.join(here, "checkpoints"))
    parser.add_argument("--decode-every", type=int, default=60, metavar="N",
                        help="Run audio_decode every N steps. Always decodes on steps "
                             "that finish a request.")
    args = parser.parse_args()
    if args.decode_every < 1:
        parser.error("--decode-every must be >= 1")

    global _runner
    _runner = ParlerTTSModelRunner(args.checkpoint, play_steps=args.decode_every)
    threading.Thread(target=inference_worker, args=(_runner, args.decode_every),
                     daemon=True).start()
    print(f"Indic Parler TTS on http://{args.host}:{args.port} "
          f"(checkpoints={args.checkpoint}, decode_every={args.decode_every})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
