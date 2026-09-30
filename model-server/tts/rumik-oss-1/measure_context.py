"""How much left context does a streamed Mimi decode need to match a whole decode?

RUMIK_DECODE_CONTEXT_FRAMES was chosen (32 frames, 2.56 s), never measured. Too
little does not error: it puts a click or a seam at every chunk boundary. This
measures it the way tts/orpheus measured its Vocos decoder -- stream real speech
through codec.StreamWindows at several context sizes, and compare each against
one whole-utterance decode of the same codes.

Real speech, not random codes: take any 24 kHz WAV (a clip the bench saved is
fine), encode it with this checkpoint's own Mimi encoder, then decode.

    docker cp /tmp/rumik-bench2/000_*.wav rumik-test:/tmp/clip.wav
    docker exec rumik-test python measure_context.py /tmp/clip.wav

Read the table for the smallest context whose peak error is inaudible;
tts/orpheus found its knee where the peak fell below ~0.01%.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import soundfile as sf
import torch
from codec import CodecLayout, FrameAssembler, StreamWindows, unit_token
from decoder import MimiRows
from transformers import MimiModel

CONTEXTS = (0, 2, 4, 8, 16, 32)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    model_path = os.getenv("RUMIK_MODEL_PATH", "/models/rumik-oss-1")
    chunk = int(os.getenv("RUMIK_DECODE_CHUNK_FRAMES", "2"))
    device = os.getenv("RUMIK_DECODER_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
    layout = CodecLayout.from_config(model_path)
    mimi = MimiModel.from_pretrained(f"{model_path}/codec").eval().to(device)

    audio, rate = sf.read(sys.argv[1], dtype="float32", always_2d=True)
    if rate != 24000:
        raise SystemExit(f"{sys.argv[1]} is {rate} Hz; Mimi here is 24 kHz")
    wav = torch.from_numpy(audio.mean(axis=1))[None, None].to(device)
    with torch.inference_mode():
        codes = mimi.encode(wav, num_quantizers=layout.num_quantizers).audio_codes[0]  # [Q, T]
    frames = codes.T.tolist()
    tokens = [unit_token(c, q, layout) for frame in frames for q, c in enumerate(frame)]

    spf = mimi.decode(codes[None, :, :4]).audio_values.shape[-1] // 4
    rows = MimiRows(mimi, spf)
    whole = np.frombuffer(rows([frames], [len(frames)])[0], "<i2").astype(np.float64)
    peak = max(np.abs(whole).max(), 1.0)
    print(f"{sys.argv[1]}: {len(frames)} frames ({len(frames) * 0.08:.2f} s), "
          f"chunk {chunk} frames, device {device}\n")
    print(f"  {'context':>7}  {'peak error':>11}  {'rms error':>10}")
    for context in CONTEXTS:
        windows = StreamWindows(FrameAssembler(layout), chunk=chunk, context=context)
        parts = []
        for t in tokens:
            pending = windows.push(t)
            if pending is not None:
                parts.append(rows([pending[0]], [pending[1]])[0])
        if (tail := windows.flush()) is not None:
            parts.append(rows([tail[0]], [tail[1]])[0])
        streamed = np.frombuffer(b"".join(parts), "<i2").astype(np.float64)
        err = np.abs(streamed - whole)
        print(f"  {context:>7}  {100 * err.max() / peak:>10.3f}%  "
              f"{100 * np.sqrt((err ** 2).mean()) / peak:>9.4f}%")


if __name__ == "__main__":
    main()
