"""Hima-ASR in the STT slot.

Hima-ASR (https://huggingface.co/Prahaladha/hima-asr) is a 0.46B encoder-decoder:
Qwen3-ASR's audio encoder, a projector, and a Gemma-3-270M text decoder. It is a
plain HuggingFace Transformers model loaded with ``trust_remote_code`` -- no NeMo,
no vLLM -- and it transcribes whole clips, 1 to 30 s at 16 kHz. It does not stream.

So this server follows indic-conformer's shape, not Nemotron's:

* ``POST /v1/audio/transcriptions``  OpenAI-shaped; one WAV per request.
* ``WS /v1/realtime?intent=transcription``  OpenAI Realtime transcription. Partials
  come from re-transcribing the open segment every ``REALTIME_INTERIM_MS``
  (realtime_ws.py, shared with indic-conformer), which is what every STT
  provider in apps/providers/local/ already speaks.
* ``GET /health``  503 until the model is loaded and warmed.
* ``GET /v1/languages``  what the demo page populates itself from.
* ``GET /demo``  the same live demo page indic-conformer serves.

Every request -- POST and realtime alike -- goes through one batch worker, so
concurrent calls share a forward pass instead of queueing behind each other.

What is deliberately NOT here: the model card's decision head (tone, intent,
urgency). It is a separate 17.5M model with its own API, and it does not belong
in a slot whose contract is "audio in, text out".
"""

from __future__ import annotations

import asyncio
import io
import os
import queue
import threading
import time
import traceback
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from realtime_ws import RealtimeDeps, active_session_count, handle_realtime_ws

# =========================
# Configuration -- every variable is also declared in compose.extra.yml, so
# nothing here is set by whatever a library happens to default to.
# =========================

MODEL_ID = "hima-asr"
MODEL_PATH = os.environ.get("HIMA_MODEL_PATH", "/app/models/hima-asr")
DTYPE_NAME = os.environ.get("HIMA_DTYPE", "float32").strip().lower()
DEVICE = os.environ.get("HIMA_DEVICE", "").strip() or (
    "cuda:0" if torch.cuda.is_available() else "cpu"
)
STYLE = os.environ.get("HIMA_STYLE", "native").strip().lower()
MAX_BATCH_SIZE = int(os.environ.get("HIMA_MAX_BATCH", "16"))
BATCH_TIMEOUT = int(os.environ.get("HIMA_BATCH_WINDOW_MS", "50")) / 1000
# The model card's limit. Longer audio is split (see split_long_audio) rather
# than handed to a model that was never trained on it.
MAX_SECONDS = float(os.environ.get("HIMA_MAX_SECONDS", "30"))
QUEUE_MAXSIZE = int(os.environ.get("HIMA_QUEUE_MAXSIZE", "256"))

TARGET_SAMPLE_RATE = 16000
# Under 0.1 s there is nothing to transcribe, and the model card asks for >= 1 s.
# 0.1 s keeps a very short interim from erroring while still skipping silence.
MIN_SAMPLES = 1600

# Wire codes the checkpoint was trained on. Odia is `or` here and `od` in
# VoicEra; the provider translates, and `od` is accepted too so a caller that
# forgets cannot get a silent mis-decode.
LANGUAGES: dict[str, str] = {
    "as": "Assamese",
    "bn": "Bengali",
    "en": "English",
    "gu": "Gujarati",
    "hi": "Hindi",
    "kn": "Kannada",
    "ml": "Malayalam",
    "mr": "Marathi",
    "or": "Odia",
    "pa": "Punjabi",
    "ta": "Tamil",
    "te": "Telugu",
}
_ALIASES = {"od": "or"}
# "auto" (or an empty language) asks the model to identify the language itself.
# The VoicEra provider never sends it -- an agent always names its language --
# but a raw API caller may.
AUTO = "auto"
STYLES = ("native", "mixed")


class UnsupportedLanguage(ValueError):
    pass


def normalize_language(language: str | None) -> str:
    """Map a request's language to a wire code, or AUTO. Raises on unknown codes."""
    lang = (language or "").strip().lower().split("-")[0]
    if not lang or lang == AUTO:
        return AUTO
    lang = _ALIASES.get(lang, lang)
    if lang not in LANGUAGES:
        raise UnsupportedLanguage(
            f"language '{language}' is not supported by {MODEL_ID}; "
            f"expected one of {sorted(LANGUAGES)} or '{AUTO}'"
        )
    return lang


# =========================
# Long audio
# =========================


def split_long_audio(
    audio: np.ndarray,
    max_samples: int,
    search_samples: int = 3 * TARGET_SAMPLE_RATE,
    frame: int = 320,
) -> list[np.ndarray]:
    """Split audio longer than the model's window at the quietest point near each cut.

    A turn on a phone line rarely reaches 30 s -- Silero ends it first -- but a
    POST upload can be any length, and the model card is explicit that clips
    stop at 30 s. A fixed cut lands mid-word; looking back up to
    ``search_samples`` for the lowest-energy 20 ms frame usually lands in a pause.
    """
    if len(audio) <= max_samples:
        return [audio]
    pieces: list[np.ndarray] = []
    start = 0
    while len(audio) - start > max_samples:
        end = start + max_samples
        lo = max(start + max_samples - search_samples, start + frame)
        window = audio[lo:end]
        n_frames = len(window) // frame
        if n_frames > 0:
            energy = (window[: n_frames * frame].reshape(n_frames, frame) ** 2).mean(axis=1)
            end = lo + int(np.argmin(energy)) * frame + frame // 2
        pieces.append(audio[start:end])
        start = end
    pieces.append(audio[start:])
    return pieces


# =========================
# Model
# =========================

model = None
_last_worker_error: str | None = None


def _torch_dtype(name: str):
    try:
        return {"float32": torch.float32, "bfloat16": torch.bfloat16, "float16": torch.float16}[
            name
        ]
    except KeyError:
        raise RuntimeError(
            f"HIMA_DTYPE must be float32, bfloat16 or float16, not '{name}'"
        ) from None


def load_model():
    """Load from the folder fetch.sh filled. Never from the network.

    ``trust_remote_code`` runs the repo's own modeling file, which is why
    fetch.sh pins a commit and the image sets HF_HUB_OFFLINE: the code that runs
    is the code that was reviewed, not whatever the repo holds today.
    """
    from transformers import AutoModel

    path = Path(MODEL_PATH)
    if not (path / "model.safetensors").is_file():
        raise RuntimeError(
            f"no checkpoint at {path}. Run model-server/stt/hima-asr/fetch.sh before "
            "starting the slot."
        )
    m = AutoModel.from_pretrained(str(path), trust_remote_code=True, dtype=_torch_dtype(DTYPE_NAME))
    return m.to(DEVICE).eval()


def warmup(m) -> None:
    """One decode before /health says yes, so the first caller is not the one who
    pays for CUDA context creation and kernel selection."""
    with torch.no_grad():
        m.transcribe([np.zeros(TARGET_SAMPLE_RATE, dtype=np.float32)], language="hi")


def _transcribe_group(audio_arrays: list[np.ndarray], language: str) -> list[str]:
    """One model call for clips that share a language. Long clips are split and
    their pieces rejoined, inside the same call."""
    results = [""] * len(audio_arrays)
    flat: list[np.ndarray] = []
    owner: list[int] = []
    max_samples = int(MAX_SECONDS * TARGET_SAMPLE_RATE)
    for i, arr in enumerate(audio_arrays):
        if len(arr) < MIN_SAMPLES:
            continue
        for piece in split_long_audio(arr, max_samples):
            if len(piece) >= MIN_SAMPLES:
                flat.append(piece)
                owner.append(i)
    if not flat:
        return results

    with torch.no_grad():
        texts = model.transcribe(
            flat,
            language=None if language == AUTO else language,
            style=STYLE,
            batch_size=len(flat),
        )
    if isinstance(texts, str):
        texts = [texts]

    parts: dict[int, list[str]] = defaultdict(list)
    for idx, text in zip(owner, texts, strict=True):
        if text:
            parts[idx].append(str(text).strip())
    for idx, chunks in parts.items():
        results[idx] = " ".join(c for c in chunks if c)
    return results


class InferenceFailed(RuntimeError):
    """Put on a response queue when the batch could not be decoded, so the caller
    gets an error instead of waiting forever on a queue nobody will fill."""


def infer(batch: list[dict]) -> list[str | BaseException]:
    """Run a batch, one model call per language.

    A failure is confined to its language group: one session asking for
    something the model chokes on must not fail every other caller who
    happened to share its batch window.
    """
    groups: dict[str, list[int]] = defaultdict(list)
    for i, item in enumerate(batch):
        groups[item["language_id"]].append(i)

    results: list[str | BaseException] = [""] * len(batch)
    for lang, indices in groups.items():
        try:
            texts = _transcribe_group([batch[i]["audio_np"] for i in indices], lang)
        except Exception as exc:  # noqa: BLE001
            global _last_worker_error
            _last_worker_error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            texts = [InferenceFailed(_last_worker_error)] * len(indices)
        for i, text in zip(indices, texts, strict=True):
            results[i] = text
    return results


# =========================
# Batch worker
# =========================

request_queue: queue.Queue = queue.Queue(maxsize=QUEUE_MAXSIZE)


def batch_worker() -> None:
    while True:
        # Block for the first item, THEN open the window. Starting the clock
        # before the blocking get would leave it already expired after any idle
        # spell, and every batch after a quiet moment would be a batch of one.
        batch = [request_queue.get()]
        start = time.time()
        while len(batch) < MAX_BATCH_SIZE:
            remaining = BATCH_TIMEOUT - (time.time() - start)
            if remaining <= 0:
                break
            try:
                batch.append(request_queue.get(timeout=remaining))
            except queue.Empty:
                break
        try:
            results = infer(batch)
        except Exception as exc:  # noqa: BLE001 -- never let the worker die
            traceback.print_exc()
            results = [InferenceFailed(f"{type(exc).__name__}: {exc}")] * len(batch)
        for item, result in zip(batch, results, strict=True):
            item["response_queue"].put(result)


def enqueue(req_q: queue.Queue, audio_np: np.ndarray, language_id: str) -> queue.Queue:
    response_queue: queue.Queue = queue.Queue(maxsize=1)
    try:
        req_q.put(
            {"audio_np": audio_np, "language_id": language_id, "response_queue": response_queue},
            timeout=1.0,
        )
    except queue.Full:
        raise HTTPException(status_code=503, detail="STT queue is full") from None
    return response_queue


def _unwrap(result):
    if isinstance(result, BaseException):
        raise HTTPException(status_code=503, detail=f"transcription failed: {result}")
    return result


class _RealtimeLanguageRouter:
    """realtime_ws.py asks for a queue per language before it enqueues. That is
    where an unsupported language is rejected: a RuntimeError there becomes an
    `error` event plus a closed turn, rather than a batch failure."""

    def __call__(self, language: str) -> queue.Queue:
        try:
            normalize_language(language)
        except UnsupportedLanguage as exc:
            raise RuntimeError(str(exc)) from exc
        return request_queue


def _realtime_enqueue(req_q: queue.Queue, audio_np: np.ndarray, language: str) -> queue.Queue:
    return enqueue(req_q, audio_np, normalize_language(language))


def _realtime_deps() -> RealtimeDeps:
    return RealtimeDeps(
        min_samples=MIN_SAMPLES,
        target_sample_rate=TARGET_SAMPLE_RATE,
        # realtime_ws.py is shared with indic-conformer, which has a Bhili
        # checkpoint. This model has none, so Bhili is simply not a language.
        bhili_enabled=False,
        bhili_loaded=False,
        is_bhili_language=lambda _lang: False,
        request_queue_for=_RealtimeLanguageRouter(),
        enqueue=_realtime_enqueue,
        queue_full_error=HTTPException,
    )


# =========================
# App
# =========================


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Load, warm, then start the worker. /health stays 503 until all three are done."""
    global model
    loaded = await asyncio.to_thread(load_model)
    await asyncio.to_thread(warmup, loaded)
    model = loaded
    threading.Thread(target=batch_worker, daemon=True).start()
    yield


app = FastAPI(title="hima-asr", lifespan=lifespan)
STATIC = Path(__file__).resolve().parent / "static"


@app.get("/health")
def health():
    body = {
        "status": "healthy" if model is not None else "loading",
        "model": MODEL_ID,
        "device": DEVICE,
        "dtype": DTYPE_NAME,
        "style": STYLE,
        "max_seconds": MAX_SECONDS,
        "queue_size": request_queue.qsize(),
        "realtime_sessions_active": active_session_count(),
        "max_batch_size": MAX_BATCH_SIZE,
        "batch_window_ms": int(BATCH_TIMEOUT * 1000),
        "last_worker_error": _last_worker_error,
    }
    if model is None:
        return JSONResponse(status_code=503, content=body)
    return body


@app.get("/v1/languages")
def languages():
    return {
        "count": len(LANGUAGES),
        "auto_detect": True,
        "styles": list(STYLES),
        "languages": [{"code": c, "name": n} for c, n in LANGUAGES.items()],
    }


@app.get("/demo")
def demo_page():
    page = STATIC / "realtime.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="demo page not installed")
    return FileResponse(page)


@app.websocket("/v1/realtime")
async def realtime_transcription(ws: WebSocket):
    await handle_realtime_ws(ws, _realtime_deps())


def _resample(x: np.ndarray, sr: int) -> np.ndarray:
    if sr == TARGET_SAMPLE_RATE or x.size == 0:
        return x.astype(np.float32)
    n_out = int(len(x) * TARGET_SAMPLE_RATE / sr)
    idx = np.linspace(0, len(x) - 1, n_out)
    return np.interp(idx, np.arange(len(x)), x).astype(np.float32)


def pcm_from_upload(raw: bytes) -> np.ndarray:
    """A WAV (any rate, any channel count) or, for parity with indic-conformer,
    headerless 16 kHz int16 PCM. Returns float32 mono at 16 kHz."""
    if raw[:4] == b"RIFF":
        import soundfile as sf

        data, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
        return _resample(data.mean(axis=1), sr)
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


@app.post("/v1/audio/transcriptions")
async def openai_transcriptions(
    file: UploadFile = File(...),
    model_name: str = Form(default="", alias="model"),  # noqa: ARG001 -- OpenAI shape
    language: str = Form(default=AUTO),
):
    if model is None:
        raise HTTPException(status_code=503, detail="model is loading")
    try:
        lang = normalize_language(language)
    except UnsupportedLanguage as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audio_np = pcm_from_upload(await file.read())
    response_queue = enqueue(request_queue, audio_np, lang)
    text = _unwrap(await asyncio.to_thread(response_queue.get))
    return {"text": text}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8001")))
