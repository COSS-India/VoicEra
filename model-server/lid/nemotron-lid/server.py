#!/usr/bin/env python3
"""Nemotron LID slot: spoken language ID only (no streaming ASR).

  GET  /health     — slot healthcheck (model-server convention)
  POST /identify   — multipart audio → language_code + confidence

VoicEra runtime posts WAV here via the gateway at /v1/lid/identify.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from nemotron_lid import (  # noqa: E402
    SAMPLE_RATE,
    load_audio_16k_mono,
    load_encoder,
    load_probe,
    resolve_nemo_checkpoint,
    run_lid,
)

PROBE_DIR = _ROOT / "probe"

app = FastAPI(title="Nemotron LID", version="1.0.0")
_state: dict = {}
_infer_lock = threading.Lock()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    # Slot convention: PORT from Compose (8004). Hardcoding would fight the gateway.
    p.add_argument("--port", type=int, default=int(os.getenv("PORT", "8004")))
    p.add_argument("--device", default=os.getenv("DEVICE", "cuda" if torch.cuda.is_available() else "cpu"))
    p.add_argument("--probe-dir", type=Path, default=Path(os.getenv("LID_PROBE_DIR", str(PROBE_DIR))))
    return p.parse_args()


def decode_audio_bytes(data: bytes, filename: str = "") -> np.ndarray:
    name = (filename or "").lower()
    if data[:4] == b"RIFF" or name.endswith(".wav"):
        with wave.open(io.BytesIO(data), "rb") as wf:
            nch = wf.getnchannels()
            sw = wf.getsampwidth()
            sr = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        if sw == 2:
            pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif sw == 4:
            pcm = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            raise ValueError(f"unsupported WAV sample width {sw}")
        if nch > 1:
            pcm = pcm.reshape(-1, nch).mean(axis=1)
        if sr != SAMPLE_RATE:
            duration = pcm.size / float(sr)
            n_out = max(1, int(round(duration * SAMPLE_RATE)))
            t_in = np.linspace(0.0, duration, num=pcm.size, endpoint=False)
            t_out = np.linspace(0.0, duration, num=n_out, endpoint=False)
            pcm = np.interp(t_out, t_in, pcm).astype(np.float32)
        return np.ascontiguousarray(pcm, dtype=np.float32)

    suffix = ".mp3"
    for ext in (".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wav"):
        if name.endswith(ext):
            suffix = ext
            break
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        return load_audio_16k_mono(Path(tmp.name))


@app.get("/health")
def health():
    return {
        "ok": bool(_state.get("model")),
        "device": _state.get("device"),
        "languages": _state.get("langs", []),
        "lang_codes": _state.get("codes", {}),
        "mode": "lid_identify",
        "nemo_path": _state.get("nemo_path"),
    }


@app.post("/identify")
async def identify(
    audio: UploadFile = File(..., description="Audio file"),
    filename: str | None = Form(default=None),
):
    if not _state.get("model"):
        raise HTTPException(503, "model not loaded")
    data = await audio.read()
    if not data:
        raise HTTPException(400, "empty audio upload")
    name = filename or audio.filename or "upload.wav"
    try:
        pcm = decode_audio_bytes(data, name)
    except Exception as e:
        raise HTTPException(400, f"audio decode failed: {e}") from e
    if pcm.size < int(0.2 * SAMPLE_RATE):
        raise HTTPException(400, "audio too short (<0.2 s)")

    with _infer_lock:
        result = run_lid(
            _state["model"],
            _state["clf"],
            _state["langs"],
            _state["codes"],
            pcm,
            _state["device"],
            use_fp16=False,
        )
    return {
        "detected_language": result.language,
        "language_code": result.lang_code,
        "confidence": result.confidence,
        "probabilities": result.probabilities,
        "duration_sec": result.duration_s,
        "encoder_ms": round(result.encoder_s * 1000, 2),
        "lid_ms": round(result.lid_s * 1000, 2),
        "total_ms": round(result.total_s * 1000, 2),
    }


def main() -> int:
    args = parse_args()
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        print("WARNING: CUDA unavailable — using CPU", file=sys.stderr)
        args.device = "cpu"

    nemo_path = resolve_nemo_checkpoint(verify_hash=True)
    # Encoder-only: LID does not need the RNNT decoder / streaming session.
    model = load_encoder(nemo_path, device=args.device)
    clf, langs, codes = load_probe(args.probe_dir)

    _state.update(
        {
            "model": model,
            "clf": clf,
            "langs": langs,
            "codes": codes,
            "device": args.device,
            "nemo_path": str(nemo_path),
        }
    )
    print(f"Nemotron LID ready device={args.device} langs={langs} nemo={nemo_path}")

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
