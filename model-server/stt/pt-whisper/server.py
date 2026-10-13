"""pt-whisper: Brazilian Portuguese STT for the model-server STT slot.

Serves BuzzASR/portuguese (a Whisper-large-v3 fine-tune) with the same wire
contract as indic-nemotron, so the platform's existing streaming client works
unchanged:

    WS   /v1/asr/ws?language=pt     PCM16 mono 16 kHz in, JSON transcripts out
    POST /v1/audio/transcriptions   OpenAI-shaped, one WAV per request
    GET  /health                    200 once the model is loaded
    GET  /demo                      a minimal upload page

Whisper cannot decode incrementally, so partial transcripts are produced here,
server-side: while audio is arriving the open segment is re-transcribed every
PTW_INTERIM_MS, behind Silero VAD so silence never reaches the decoder (Whisper
hallucinates on silence). The caller decides where an utterance ends -- the
Pipecat pipeline sends {"action": "flush_eos"} on its own VAD stop, exactly as
it does for Nemotron -- and gets back one {"is_final": true} message.

Every environment variable read here is declared in the Dockerfile; see
tests/test_engine_env_surface.py for why that matters.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from scipy.signal import resample_poly
from starlette.websockets import WebSocketState

log = logging.getLogger("pt-whisper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# ---------------------------------------------------------------- settings

MODEL_DIR = os.getenv("PTW_MODEL_DIR", "/app/models/portuguese")
MODEL_ID = os.getenv("PTW_MODEL_ID", "pt-whisper")
INTERIM_MS = int(os.getenv("PTW_INTERIM_MS", "600"))
MAX_BUFFER_S = float(os.getenv("PTW_MAX_BUFFER_S", "28"))
VAD_THRESHOLD = float(os.getenv("PTW_VAD_THRESHOLD", "0.5"))
NUM_BEAMS = int(os.getenv("PTW_NUM_BEAMS", "1"))
CUDA_MEM_GB = float(os.getenv("PTW_CUDA_MEM_GB", "0") or 0)

SAMPLE_RATE = 16000
LANGUAGES = {"pt", "pt-br", "pt_br"}   # one checkpoint, one language
PRE_ROLL_S = 0.3                        # keep a little audio before VAD's start

# ---------------------------------------------------------------- model

_state: dict = {"model": None, "processor": None, "vad": None, "device": "cpu"}
_gpu_lock = threading.Lock()   # one decode at a time on the card
_vad_lock = threading.Lock()   # Silero's JIT model is stateful


def _load() -> None:
    from silero_vad import load_silero_vad
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and CUDA_MEM_GB > 0:
        total = torch.cuda.get_device_properties(0).total_memory
        frac = min(1.0, CUDA_MEM_GB * (1024 ** 3) / total)
        torch.cuda.set_per_process_memory_fraction(frac, 0)
        log.info("CUDA memory capped at %.1f GB (fraction %.3f)", CUDA_MEM_GB, frac)

    dtype = torch.float16 if device == "cuda" else torch.float32
    log.info("loading %s on %s", MODEL_DIR, device)
    processor = WhisperProcessor.from_pretrained(MODEL_DIR)
    model = WhisperForConditionalGeneration.from_pretrained(
        MODEL_DIR, torch_dtype=dtype, attn_implementation="sdpa").to(device).eval()

    _state.update(model=model, processor=processor, vad=load_silero_vad(), device=device)
    # Warm up so the first caller does not pay for CUDA kernel selection.
    _transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), skip_vad=True)
    log.info("ready")


def _speech_bounds(audio: np.ndarray) -> tuple[int, int] | None:
    """First speech start and last speech end, in samples; None if no speech."""
    from silero_vad import get_speech_timestamps

    with _vad_lock:
        stamps = get_speech_timestamps(
            torch.from_numpy(audio), _state["vad"], sampling_rate=SAMPLE_RATE,
            threshold=VAD_THRESHOLD, min_speech_duration_ms=150)
    if not stamps:
        return None
    return stamps[0]["start"], stamps[-1]["end"]


def _transcribe(audio: np.ndarray, skip_vad: bool = False) -> str:
    """Float32 mono 16 kHz in, text out. Blocking -- call via a thread."""
    if audio.size < SAMPLE_RATE // 10:
        return ""
    if not skip_vad:
        bounds = _speech_bounds(audio)
        if bounds is None:
            return ""
        start = max(0, bounds[0] - int(PRE_ROLL_S * SAMPLE_RATE))
        audio = audio[start: bounds[1] + int(PRE_ROLL_S * SAMPLE_RATE)]

    model, processor, device = _state["model"], _state["processor"], _state["device"]
    feats = processor(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt").input_features
    feats = feats.to(device, dtype=model.dtype)
    with _gpu_lock, torch.inference_mode():
        # Generation settings from the model card.
        ids = model.generate(
            feats, num_beams=NUM_BEAMS, no_repeat_ngram_size=3,
            repetition_penalty=1.2, max_new_tokens=220,
            language="pt", task="transcribe")
    return processor.batch_decode(ids, skip_special_tokens=True)[0].strip()


def _pcm16_to_float(pcm: bytes) -> np.ndarray:
    if len(pcm) % 2:
        pcm = pcm[:-1]
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(_load)
    yield


app = FastAPI(title="pt-whisper", lifespan=lifespan)

# ---------------------------------------------------------------- HTTP


@app.get("/health")
async def health():
    if _state["model"] is None:
        return JSONResponse({"status": "loading"}, status_code=503)
    return {"status": "healthy", "model": MODEL_ID, "device": _state["device"],
            "interim_ms": INTERIM_MS, "languages": sorted(LANGUAGES)}


@app.get("/v1/languages")
async def languages():
    return {"languages": ["pt"]}


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model: str = Form(MODEL_ID),
    language: str = Form("pt"),
    response_format: str = Form("json"),
):
    raw = await file.read()
    try:
        audio, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
    except Exception:
        return JSONResponse(
            {"error": "expected an audio file (WAV); headerless PCM cannot state its rate"},
            status_code=415)
    audio = audio.mean(axis=1)
    if rate != SAMPLE_RATE:
        g = np.gcd(int(rate), SAMPLE_RATE)
        audio = resample_poly(audio, SAMPLE_RATE // g, int(rate) // g).astype(np.float32)
    # Long uploads: transcribe in 28 s windows so nothing past 30 s is dropped.
    step = int(MAX_BUFFER_S * SAMPLE_RATE)
    parts = []
    for i in range(0, max(len(audio), 1), step):
        parts.append(await asyncio.to_thread(_transcribe, audio[i:i + step]))
    text = " ".join(p for p in parts if p)
    if response_format == "text":
        return PlainTextResponse(text)
    return {"text": text}


DEMO = """<!doctype html><meta charset=utf-8><title>pt-whisper</title>
<style>body{font:16px system-ui;max-width:640px;margin:40px auto;padding:0 16px}</style>
<h1>pt-whisper</h1><p>Upload a WAV file of Brazilian Portuguese speech.</p>
<input type=file id=f accept="audio/wav"> <button id=b>Transcribe</button>
<pre id=o></pre>
<script>
b.onclick=async()=>{if(!f.files[0])return;o.textContent='...';
const d=new FormData();d.append('file',f.files[0]);d.append('model','pt-whisper');
const r=await fetch('/v1/audio/transcriptions',{method:'POST',body:d});
o.textContent=JSON.stringify(await r.json(),null,2)}
</script>"""


@app.get("/demo", response_class=HTMLResponse)
async def demo():
    return DEMO


# ---------------------------------------------------------------- WebSocket


class Session:
    """One caller's open utterance."""

    def __init__(self, ws: WebSocket, language: str):
        self.id = str(uuid.uuid4())
        self.ws = ws
        self.language = language
        self.buf = bytearray()
        self.gen = 0                 # bumped on flush/reset; stale interims are dropped
        self.last_interim_at = 0.0
        self.last_interim_text = ""
        self.interim_task: asyncio.Task | None = None
        self.send_lock = asyncio.Lock()
        self.max_bytes = int(MAX_BUFFER_S * SAMPLE_RATE) * 2

    async def send(self, payload: dict) -> None:
        async with self.send_lock:
            if self.ws.client_state == WebSocketState.CONNECTED:
                await self.ws.send_json({"session_id": self.id, **payload})

    def append(self, pcm: bytes) -> None:
        self.buf.extend(pcm)
        if len(self.buf) > self.max_bytes:
            del self.buf[: len(self.buf) - self.max_bytes]

    def reset(self) -> None:
        self.gen += 1
        self.buf.clear()
        self.last_interim_text = ""
        self.last_interim_at = 0.0

    def maybe_interim(self) -> None:
        now = time.monotonic()
        if (now - self.last_interim_at) * 1000 < INTERIM_MS:
            return
        if self.interim_task and not self.interim_task.done():
            return                  # the previous one is still decoding
        self.last_interim_at = now
        self.interim_task = asyncio.create_task(self._interim(self.gen, bytes(self.buf)))

    async def _interim(self, gen: int, pcm: bytes) -> None:
        try:
            text = await asyncio.to_thread(_transcribe, _pcm16_to_float(pcm))
        except Exception as e:   # never let a partial take the socket down
            log.warning("interim failed: %s", e)
            return
        if gen != self.gen or not text or text == self.last_interim_text:
            return
        self.last_interim_text = text
        await self.send({"text": text, "is_final": False, "language": self.language})

    async def flush(self) -> None:
        pcm = bytes(self.buf)
        self.reset()                 # stale interims from here on are dropped
        t0 = time.perf_counter()
        try:
            text = await asyncio.to_thread(_transcribe, _pcm16_to_float(pcm))
        except Exception as e:
            log.error("final failed: %s", e)
            text = ""
        await self.send({"text": text, "is_final": True, "language": self.language,
                         "latency_ms": round((time.perf_counter() - t0) * 1000, 1)})


@app.websocket("/v1/asr/ws")
async def asr_ws(ws: WebSocket):
    await ws.accept()
    language = (ws.query_params.get("language") or "pt").strip().lower()
    if language not in LANGUAGES:
        await ws.send_json({"error": f"unsupported language {language!r}; this model serves pt"})
        await ws.close(code=1008)
        return
    if _state["model"] is None:
        await ws.send_json({"error": "model is still loading"})
        await ws.close(code=1013)
        return

    s = Session(ws, "pt")
    await s.send({"status": "ready", "language": "pt", "expected_sample_rate": SAMPLE_RATE,
                  "interim_ms": INTERIM_MS})
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes"):
                s.append(msg["bytes"])
                s.maybe_interim()
                continue
            if not msg.get("text"):
                continue
            try:
                payload = json.loads(msg["text"])
            except json.JSONDecodeError:
                continue
            action = payload.get("action")
            if action in ("flush_eos", "eos"):
                await s.flush()
            elif action == "set_language":
                lang = str(payload.get("language", "")).strip().lower()
                if lang in LANGUAGES:
                    await s.send({"status": "language_updated", "language": "pt"})
                else:
                    await s.send({"status": "language_rejected", "language": lang,
                                  "error": "this model serves pt only"})
            elif action == "hello":
                rate = payload.get("sampleRate")
                ok = rate is not None and abs(float(rate) - SAMPLE_RATE) < 1.0
                await s.send({"status": "hello_ack" if ok else "sample_rate_mismatch",
                              "client_sample_rate": rate,
                              "expected_sample_rate": SAMPLE_RATE})
            elif action == "reset":
                s.reset()
                await s.send({"status": "session_reset"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.error("session %s: %s", s.id, e)
    finally:
        s.gen += 1
        if s.interim_task and not s.interim_task.done():
            s.interim_task.cancel()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8001")))
