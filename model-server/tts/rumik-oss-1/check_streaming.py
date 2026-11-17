"""Does the streaming decoder reproduce a one-shot decode on this checkpoint?

streaming.MimiStreamer is checked in tests/ against MimiModel.decode on a
random model. This runs the same comparison on the real weights and real
speech, which is the check that matters: take any 24 kHz WAV (a clip the load
bench saved is fine), encode it with this checkpoint's own Mimi, decode it
once whole, then stream it back in chunks -- several streams at once, started
at different times, as the server does -- and compare.

    docker cp /tmp/rumik-bench2/000_*.wav rumik-test:/tmp/clip.wav
    docker exec rumik-test python check_streaming.py /tmp/clip.wav

Everything is compared with a float32 one-shot decode. A float32 stream should
match it to float noise (well under 0.01% of peak); a bfloat16 stream should
sit where bfloat16's own one-shot decode sits, which shows what bfloat16 costs
in fidelity on this checkpoint (RUMIK_DECODER_DTYPE). It also times a batched
step at several widths, early and late in an utterance, in both precisions:
the late column should not grow, which is the streaming constraint.
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import soundfile as sf
import torch
from streaming import Chunk, MimiStreamer
from transformers import MimiModel


def streamed(mimi, frames, chunk, starts=(0, 3, 7)):
    """The same utterance as several streams joining at different ticks."""
    streamer = MimiStreamer(mimi, slots=len(starts))
    outs: list[list[bytes]] = [[] for _ in starts]
    cursor = [0] * len(starts)
    tick = 0
    while any(c < len(frames) for c in cursor):
        batch, who = [], []
        for s, offset in enumerate(starts):
            if tick >= offset and cursor[s] < len(frames):
                part = frames[cursor[s]:cursor[s] + chunk]
                batch.append(Chunk(slot=s, frames=part, start=cursor[s] == 0))
                who.append(s)
                cursor[s] += len(part)
        for s, pcm in zip(who, streamer.step(batch), strict=True):
            outs[s].append(pcm)
        tick += 1
    return [np.frombuffer(b"".join(o), "<i2").astype(np.float64) for o in outs]


def whole(mimi, codes) -> np.ndarray:
    with torch.inference_mode():
        audio = mimi.decode(codes[None].to(mimi.device)).audio_values[0, 0]
    return np.clip(audio.float().cpu().numpy(), -1.0, 1.0) * 32767.0


def step_ms(mimi, width: int, chunk: int, device: str) -> tuple[float, float]:
    """Median step time early (frames 2-10) and late (~frame 200) in an utterance."""
    streamer = MimiStreamer(mimi, slots=width)
    silence = [[0] * 8 for _ in range(chunk)]
    timings = []
    for position in range(0, 200, chunk):
        batch = [Chunk(slot=s, frames=silence, start=position == 0) for s in range(width)]
        if device == "cuda":
            torch.cuda.synchronize()
        began = time.perf_counter()
        streamer.step(batch)
        if device == "cuda":
            torch.cuda.synchronize()
        timings.append((time.perf_counter() - began) * 1000.0)
    return float(np.median(timings[1:6])), float(np.median(timings[-5:]))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    model_path = os.getenv("RUMIK_MODEL_PATH", "/models/rumik-oss-1")
    chunk = int(os.getenv("RUMIK_DECODE_CHUNK_FRAMES", "2"))
    device = os.getenv("RUMIK_DECODER_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
    models = {name: MimiModel.from_pretrained(f"{model_path}/codec", dtype=getattr(torch, name))
              .eval().to(device) for name in ("float32", "bfloat16")}

    audio, rate = sf.read(sys.argv[1], dtype="float32", always_2d=True)
    if rate != 24000:
        raise SystemExit(f"{sys.argv[1]} is {rate} Hz; Mimi here is 24 kHz")
    wav = torch.from_numpy(audio.mean(axis=1))[None, None].to(device)
    with torch.inference_mode():
        codes = models["float32"].encode(wav, num_quantizers=8).audio_codes[0].cpu()  # [Q, T]
    frames = codes.T.tolist()
    reference = whole(models["float32"], codes)
    peak = max(np.abs(reference).max(), 1.0)
    print(f"{sys.argv[1]}: {len(frames)} frames ({len(frames) * 0.08:.2f} s), "
          f"chunk {chunk} frames, {device}\n")

    def row(name: str, got: np.ndarray) -> None:
        err = np.abs(got - reference[: len(got)])
        print(f"  {name:<34} {100 * err.max() / peak:>9.4f}%  "
              f"{100 * np.sqrt((err ** 2).mean()) / peak:>9.5f}%")

    print(f"  {'against a float32 one-shot decode':<34} {'peak':>10}  {'rms':>9}")
    row("float32 streamed (3 streams, worst)", max(
        streamed(models["float32"], frames, chunk),
        key=lambda g: np.abs(g - reference[: len(g)]).max()))
    row("bfloat16 one-shot (upstream's path)", whole(models["bfloat16"], codes))
    row("bfloat16 streamed (3 streams, worst)", max(
        streamed(models["bfloat16"], frames, chunk),
        key=lambda g: np.abs(g - reference[: len(g)]).max()))

    print(f"\n  {'dtype':<9} {'width':>5}  {'step at frame 2':>15}  {'step at frame 200':>17}")
    for name, mimi in models.items():
        for width in (1, 16, 64, 128):
            early, late = step_ms(mimi, width, chunk, device)
            print(f"  {name:<9} {width:>5}  {early:>12.2f} ms  {late:>14.2f} ms")


if __name__ == "__main__":
    main()
