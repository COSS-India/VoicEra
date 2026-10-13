"""pt-chatterbox: Brazilian Portuguese TTS for the model-server TTS slot.

Serves FearL0rd/Chatterbox-TTS-Portuguese, a fine-tune of Resemble AI's
Chatterbox, behind the slot contract:

    POST /v1/audio/speech   OpenAI-shaped; streams 16-bit PCM at 24 kHz
    GET  /health            200 once the model is loaded
    GET  /demo              a minimal page to hear it

Chatterbox does not stream within an utterance. To keep the first audio as
early as possible the input is split into sentences and each one is sent the
moment it is synthesised. A client that hangs up stops the request between
sentences -- the barge-in path in the slot contract.

The voice is the checkpoint's built-in one (conds.pt). Any `voice` value is
accepted so OpenAI-style clients do not have to know that.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import threading
import wave
from contextlib import asynccontextmanager

import numpy as np
import torch
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

log = logging.getLogger("pt-chatterbox")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

MODEL_DIR = os.getenv("PTC_MODEL_DIR", "/app/checkpoints/portuguese")
MODEL_ID = os.getenv("PTC_MODEL_ID", "pt-chatterbox")
EXAGGERATION = float(os.getenv("PTC_EXAGGERATION", "0.5"))
CFG_WEIGHT = float(os.getenv("PTC_CFG_WEIGHT", "0.5"))
TEMPERATURE = float(os.getenv("PTC_TEMPERATURE", "0.8"))
MAX_CHARS = int(os.getenv("PTC_MAX_CHARS", "300"))
CUDA_MEM_GB = float(os.getenv("PTC_CUDA_MEM_GB", "0") or 0)

_state: dict = {"model": None, "sr": 24000, "device": "cpu"}
_gpu_lock = threading.Lock()


def _load() -> None:
    from chatterbox.tts import ChatterboxTTS

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and CUDA_MEM_GB > 0:
        total = torch.cuda.get_device_properties(0).total_memory
        frac = min(1.0, CUDA_MEM_GB * (1024 ** 3) / total)
        torch.cuda.set_per_process_memory_fraction(frac, 0)
        log.info("CUDA memory capped at %.1f GB (fraction %.3f)", CUDA_MEM_GB, frac)
    log.info("loading %s on %s", MODEL_DIR, device)
    model = ChatterboxTTS.from_local(MODEL_DIR, device)
    if model.conds is None:
        raise RuntimeError(f"{MODEL_DIR}/conds.pt is missing -- it holds the default voice")
    _state.update(model=model, sr=model.sr, device=device)
    _synth("Olá.")   # warm-up
    log.info("ready (sample rate %d)", model.sr)


def _synth(text: str) -> np.ndarray:
    """One sentence in, float32 mono out. Blocking -- call via a thread."""
    with _gpu_lock:
        wav = _state["model"].generate(
            text, exaggeration=EXAGGERATION, cfg_weight=CFG_WEIGHT, temperature=TEMPERATURE)
    return wav.squeeze(0).float().cpu().numpy()


def _to_pcm16(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


def split_sentences(text: str) -> list[str]:
    """Sentence-sized pieces; long ones broken at commas, then at spaces."""
    out: list[str] = []
    for sent in _SENTENCE.split(" ".join(text.split())):
        sent = sent.strip()
        while len(sent) > MAX_CHARS:
            cut = sent.rfind(", ", 0, MAX_CHARS)
            if cut < MAX_CHARS // 3:
                cut = sent.rfind(" ", 0, MAX_CHARS)
            if cut <= 0:
                cut = MAX_CHARS
            out.append(sent[: cut + 1].strip())
            sent = sent[cut + 1:].strip()
        if sent:
            out.append(sent)
    return out


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(_load)
    yield


app = FastAPI(title="pt-chatterbox", lifespan=lifespan)


@app.get("/health")
async def health():
    if _state["model"] is None:
        return JSONResponse({"status": "loading"}, status_code=503)
    return {"status": "healthy", "model": MODEL_ID, "device": _state["device"],
            "sample_rate": _state["sr"], "voices": ["default"], "languages": ["pt"]}


@app.get("/v1/voices")
async def voices():
    return {"voices": [{"name": "default", "language": "pt"}]}


class SpeechRequest(BaseModel):
    input: str
    model: str | None = None
    voice: str | None = None
    response_format: str = "pcm"
    instructions: str | None = None
    speed: float | None = None


@app.post("/v1/audio/speech")
async def speech(req: SpeechRequest, request: Request):
    fmt = (req.response_format or "pcm").lower()
    if fmt not in ("pcm", "wav"):
        return JSONResponse(
            {"error": f"response_format {fmt!r} not supported; use pcm or wav"}, status_code=400)
    pieces = split_sentences(req.input)
    if not pieces:
        return JSONResponse({"error": "input is empty"}, status_code=400)
    sr = _state["sr"]
    headers = {"X-Audio-Format": "pcm", "X-Sample-Rate": str(sr)}

    if fmt == "wav":
        # A complete file for the demo page and for smoke tests.
        chunks = [_to_pcm16(await asyncio.to_thread(_synth, p)) for p in pieces]
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(b"".join(chunks))
        return StreamingResponse(iter([buf.getvalue()]), media_type="audio/wav",
                                 headers={"X-Sample-Rate": str(sr)})

    async def stream():
        for piece in pieces:
            if await request.is_disconnected():
                log.info("client hung up; stopping after %r", piece[:40])
                return
            audio = await asyncio.to_thread(_synth, piece)
            yield _to_pcm16(audio)

    return StreamingResponse(stream(), media_type="audio/pcm", headers=headers)


DEMO = """<!doctype html><meta charset=utf-8><title>pt-chatterbox</title>
<style>body{font:16px system-ui;max-width:640px;margin:40px auto;padding:0 16px}
textarea{width:100%;height:6em}</style>
<h1>pt-chatterbox</h1>
<textarea id=t>Olá! Eu sou um assistente de voz. Como posso ajudar você hoje?</textarea>
<p><button id=b>Speak</button> <span id=s></span></p><audio id=a controls></audio>
<script>
b.onclick=async()=>{s.textContent='...';const t0=performance.now();
const r=await fetch('/v1/audio/speech',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({input:t.value,model:'pt-chatterbox',voice:'default',response_format:'wav'})});
if(!r.ok){s.textContent=await r.text();return}
a.src=URL.createObjectURL(await r.blob());a.play();
s.textContent=((performance.now()-t0)/1000).toFixed(2)+' s'}
</script>"""


@app.get("/demo", response_class=HTMLResponse)
async def demo():
    return DEMO


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8002")))
