import asyncio
import base64
import os
import queue
import threading
import traceback
import time
from pathlib import Path

import numpy as np
import torch
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from nemo.collections.asr.models import EncDecHybridRNNTCTCBPEModel
from pydantic import BaseModel

from realtime_ws import RealtimeDeps, active_session_count, handle_realtime_ws

load_dotenv()

# =========================
# FastAPI setup
# =========================

app = FastAPI()

# =========================
# Request/Response Models
# =========================

class TranscribeRequest(BaseModel):
    audio_b64: str
    language_id: str = "hi"


class TranscribeResponse(BaseModel):
    text: str

# =========================
# Model loading
# =========================

TARGET_SAMPLE_RATE = 16000
MIN_SAMPLES = 1600
QUEUE_MAXSIZE = 256
MAX_BATCH_SIZE = 16
BATCH_TIMEOUT = 0.100  # 100 ms

# Set to "yes" or "no" in .env
BHILI_ENABLE = os.environ.get("BHILI_ENABLE", "no").strip().lower()

device = "cuda:0" if torch.cuda.is_available() else "cpu"
main_model = None
bhili_model = None


def _required_model_path(env_var_name: str) -> Path:
    env_value = (os.environ.get(env_var_name) or "").strip()
    if not env_value:
        raise RuntimeError(
            f"Missing required environment variable: {env_var_name}. "
            f"Please set it in model-server/stt/.env"
        )

    path = Path(env_value).expanduser()
    if not path.is_absolute():
        path = (Path(__file__).resolve().parent / path).resolve()
    else:
        path = path.resolve()

    if not path.is_file():
        raise RuntimeError(
            f"Invalid {env_var_name}: file not found at {path}. "
            "Please update model-server/stt/.env"
        )

    return path


def load_main_model():
    model_path = _required_model_path("INDIC_NEMO_PATH")
    model = EncDecHybridRNNTCTCBPEModel.restore_from(
        restore_path=str(model_path),
        map_location=torch.device(device),   # <-- add this
    )
    model = model.to(device)
    model.freeze()
    model.cur_decoder = "rnnt"
    return model


def load_bhili_model():
    model_path = _required_model_path("BHILI_NEMO_PATH")
    model = EncDecHybridRNNTCTCBPEModel.restore_from(
        str(model_path),
        map_location=torch.device(device),
    )
    model = model.to(device)
    model.freeze()
    model.cur_decoder = "rnnt"
    return model


def _is_bhili_language(language_id: str) -> bool:
    return (language_id or "").strip().lower() in {"bhb", "bhili"}


def _nemo_language_id(language_id: str) -> str:
    if _is_bhili_language(language_id):
        return "mr"
    return language_id or "hi"


def _decode_audio_b64(audio_b64: str) -> np.ndarray:
    audio_bytes = base64.b64decode(audio_b64)
    return np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0


def _request_queue_for_language(language_id: str) -> queue.Queue:
    if _is_bhili_language(language_id):
        return bhili_request_queue
    return main_request_queue


def _enqueue_request(request_queue: queue.Queue, audio_np: np.ndarray, language_id: str) -> queue.Queue:
    response_queue = queue.Queue(maxsize=1)
    request_item = {
        "audio_np": audio_np,
        "language_id": language_id,
        "response_queue": response_queue,
    }

    try:
        request_queue.put(request_item, timeout=1.0)
    except queue.Full:
        raise HTTPException(status_code=503, detail="STT queue is full")

    return response_queue


def _unwrap(result):
    """Turn a worker failure back into an error for the caller."""
    if isinstance(result, BaseException):
        raise HTTPException(status_code=503, detail=f"transcription failed: {result}")
    return result


def _realtime_deps() -> RealtimeDeps:
    return RealtimeDeps(
        min_samples=MIN_SAMPLES,
        target_sample_rate=TARGET_SAMPLE_RATE,
        bhili_enabled=BHILI_ENABLE == "yes",
        bhili_loaded=bhili_model is not None,
        is_bhili_language=_is_bhili_language,
        request_queue_for=_request_queue_for_language,
        enqueue=_enqueue_request,
        queue_full_error=HTTPException,
    )

# =========================
# Queues and batching config
# =========================

main_request_queue = queue.Queue(maxsize=QUEUE_MAXSIZE)
bhili_request_queue = queue.Queue(maxsize=QUEUE_MAXSIZE)

# =========================
# Batcher + worker thread
# =========================

def _transcribe_batch(model, audio_arrays, language_id: str):
    valid_indices = [i for i, arr in enumerate(audio_arrays) if len(arr) >= MIN_SAMPLES]
    if not valid_indices:
        return [""] * len(audio_arrays)

    valid_audio = [audio_arrays[i] for i in valid_indices]
    with torch.no_grad():
        transcriptions = model.transcribe(
            audio=valid_audio,
            batch_size=len(valid_audio),
            language_id=language_id,
        )[0]

    results = [""] * len(audio_arrays)
    for idx, text in zip(valid_indices, transcriptions):
        results[idx] = str(text).strip() if text is not None else ""
    return results


def _infer_batch_by_language(model, batch, language_fn):
    """Run transcribe once per distinct language_id in the batch."""
    from collections import defaultdict

    groups: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for idx, item in enumerate(batch):
        groups[item["language_id"]].append((idx, item))

    results = [""] * len(batch)
    for lang, indexed in groups.items():
        indices = [i for i, _ in indexed]
        audio_arrays = [item["audio_np"] for _, item in indexed]
        nemo_lang = language_fn(lang)
        texts = _transcribe_batch(model, audio_arrays, nemo_lang)
        for idx, text in zip(indices, texts):
            results[idx] = text
    return results


def main_infer(batch):
    return _infer_batch_by_language(main_model, batch, lambda lang: lang or "hi")


def bhili_infer(batch):
    return _infer_batch_by_language(bhili_model, batch, _nemo_language_id)


class InferenceFailed(RuntimeError):
    """Put on a response queue when the batch worker could not decode.

    A batch that raised used to kill the worker thread outright. Every caller
    already waiting was left blocked on a queue nobody would ever put to, and
    every later request joined them, while /health still answered 200 and the
    container stayed `running`. Reaching a dead model was indefinite waiting
    rather than an error.
    """


#: Last batch failure, surfaced at /health so a bad model is visible.
_last_worker_error: str | None = None


def batch_worker(request_queue, infer_fn):
    """
    Collects requests, batches them, runs the model,
    and returns results to waiting callers.
    """
    while True:
        batch = []
        start = time.time()

        # Collect batch
        while len(batch) < MAX_BATCH_SIZE:
            remaining = BATCH_TIMEOUT - (time.time() - start)
            if remaining <= 0:
                break

            try:
                item = request_queue.get(timeout=remaining)
                batch.append(item)
            except queue.Empty:
                break

        if not batch:
            continue

        try:
            transcriptions = infer_fn(batch)
        except Exception as exc:                                    # noqa: BLE001
            # Fail this batch's callers and keep serving. Dying here strands
            # them forever; a CUDA OOM or one malformed array is not a reason
            # to take every future request down with it.
            global _last_worker_error
            _last_worker_error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            failure = InferenceFailed(_last_worker_error)
            for item in batch:
                item["response_queue"].put(failure)
            continue

        # Return results
        for item, text in zip(batch, transcriptions):
            item["response_queue"].put(text)


def _start_workers():
    threading.Thread(
        target=batch_worker,
        args=(main_request_queue, main_infer),
        daemon=True,
    ).start()
    if BHILI_ENABLE == "yes":
        threading.Thread(
            target=batch_worker,
            args=(bhili_request_queue, bhili_infer),
            daemon=True,
        ).start()


@app.on_event("startup")
async def startup_event():
    global main_model, bhili_model

    main_model = load_main_model()
    if BHILI_ENABLE == "yes":
        bhili_model = load_bhili_model()
    else:
        bhili_model = None
    _start_workers()

# =========================
# Routes
# =========================

STATIC = Path(__file__).resolve().parent / "static"


@app.get("/demo")
def demo_page():
    page = STATIC / "realtime.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="demo page not installed")
    return FileResponse(page)


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(request: TranscribeRequest):
    audio_np = _decode_audio_b64(request.audio_b64)
    response_queue = _enqueue_request(main_request_queue, audio_np, request.language_id)
    result = _unwrap(await asyncio.to_thread(response_queue.get))
    return TranscribeResponse(text=result)


@app.post("/transcribe/bhili", response_model=TranscribeResponse)
async def transcribe_bhili(request: TranscribeRequest):
    if BHILI_ENABLE != "yes":
        raise HTTPException(status_code=503, detail="Bhili model is disabled")
    if bhili_model is None:
        raise HTTPException(status_code=503, detail="Bhili model not loaded")

    audio_np = _decode_audio_b64(request.audio_b64)
    response_queue = _enqueue_request(bhili_request_queue, audio_np, request.language_id)
    result = _unwrap(await asyncio.to_thread(response_queue.get))
    return TranscribeResponse(text=result)


@app.get("/health")
def health():
    """503 until the model can serve, per the slot contract in the root README.

    This answered 200 before the model had loaded and 200 after a batch
    failure, so a container healthcheck could not tell either from healthy.
    """
    body = {
        "status": "healthy" if main_model is not None else "loading",
        "device": device,
        "bhili_enabled": BHILI_ENABLE,
        "main_loaded": main_model is not None,
        "bhili_loaded": bhili_model is not None,
        "main_queue_size": main_request_queue.qsize(),
        "bhili_queue_size": bhili_request_queue.qsize(),
        "realtime_sessions_active": active_session_count(),
        "max_batch_size": MAX_BATCH_SIZE,
        "batch_timeout_ms": int(BATCH_TIMEOUT * 1000),
        "last_worker_error": _last_worker_error,
    }
    if main_model is None:
        return JSONResponse(status_code=503, content=body)
    return body


@app.websocket("/v1/realtime")
async def realtime_transcription(ws: WebSocket):
    """OpenAI Realtime transcription protocol (Pipecat OpenAIRealtimeSTTService)."""
    await handle_realtime_ws(ws, _realtime_deps())


# =========================
# OpenAI-compatible route
# =========================
# A thin wrapper over the same queues and batch workers defined above. It has
# no inference path of its own, so /transcribe and /v1/audio/transcriptions
# return identical results. The original routes are left in place.


def _pcm_from_upload(raw: bytes) -> np.ndarray:
    """Accept a WAV file or headerless 16 kHz int16 PCM.

    Scaling matches _decode_audio_b64 exactly.
    """
    if raw[:4] == b"RIFF":
        import io as _io
        import wave as _wave

        with _wave.open(_io.BytesIO(raw), "rb") as wf:
            raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


@app.post("/v1/audio/transcriptions")
async def openai_transcriptions(
    file: UploadFile = File(...),
    model: str = Form(default=""),
    language: str = Form(default="hi"),
):
    audio_np = _pcm_from_upload(await file.read())

    # Same bhb routing the voice server used to do by picking a URL.
    if _is_bhili_language(language):
        if BHILI_ENABLE != "yes" or bhili_model is None:
            raise HTTPException(status_code=503, detail="Bhili model is disabled")
        request_queue = bhili_request_queue
    else:
        request_queue = main_request_queue

    response_queue = _enqueue_request(request_queue, audio_np, language)
    text = _unwrap(await asyncio.to_thread(response_queue.get))
    return {"text": text}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
