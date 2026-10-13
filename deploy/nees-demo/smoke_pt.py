"""Portuguese round trip through the nees-demo model gateway.

TTS speaks a sentence; STT transcribes it back twice -- once over the OpenAI
upload route, once over the live WebSocket the platform uses. Run it inside the
gateway container, which has httpx and websockets:

    docker exec -i nees_demo_model_gateway python - < deploy/nees-demo/smoke_pt.py
    docker cp nees_demo_model_gateway:/tmp/pt_tts.wav .   # then listen to it

Exit code 0 means every hop answered; read the printed transcripts yourself --
quality is not judged here.
"""

import asyncio
import io
import json
import sys
import time
import wave

import httpx
import websockets

GW = "http://localhost:8000"
SENTENCE = "Olá! Bom dia. Eu sou o assistente virtual. Como posso ajudar você hoje?"
OUT = "/tmp/pt_tts.wav"


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def main():
    with httpx.Client(timeout=300) as c:
        h = c.get(f"{GW}/health").json()
        print("health:", json.dumps(h))
        ids = [m["id"] for m in c.get(f"{GW}/v1/models").json()["data"]]
        print("models:", ids)
        if not {"pt-whisper", "pt-chatterbox"} <= set(ids):
            fail("both pt models must be listed")

        # ---- TTS, streamed PCM
        t0 = time.perf_counter()
        first = None
        pcm = bytearray()
        with c.stream("POST", f"{GW}/v1/audio/speech", json={
                "input": SENTENCE, "model": "pt-chatterbox", "voice": "default",
                "response_format": "pcm"}) as r:
            if r.status_code != 200:
                fail(f"tts {r.status_code}: {r.read()[:300]!r}")
            rate = int(r.headers.get("x-sample-rate", "0"))
            fmt = r.headers.get("x-audio-format")
            for chunk in r.iter_bytes():
                if first is None:
                    first = time.perf_counter() - t0
                pcm.extend(chunk)
        total = time.perf_counter() - t0
        secs = len(pcm) / 2 / max(rate, 1)
        print(f"tts: {fmt} {rate} Hz, {secs:.2f}s audio, first audio {first:.2f}s, total {total:.2f}s")
        if fmt != "pcm" or rate != 24000 or secs < 1:
            fail("unexpected TTS output")
        with wave.open(OUT, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(bytes(pcm))
        print("wrote", OUT)

        # ---- STT, OpenAI upload route
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(bytes(pcm))
        t0 = time.perf_counter()
        r = c.post(f"{GW}/v1/audio/transcriptions",
                   files={"file": ("pt.wav", buf.getvalue(), "audio/wav")},
                   data={"model": "pt-whisper", "language": "pt"})
        if r.status_code != 200:
            fail(f"stt upload {r.status_code}: {r.text[:300]}")
        print(f"stt upload ({time.perf_counter() - t0:.2f}s): {r.json()['text']!r}")
    return bytes(pcm), rate


async def live(pcm24: bytes, rate: int):
    # Downsample 24k -> 16k (2:3) crudely; good enough for a smoke test.
    import array
    src = array.array("h", pcm24)
    out = array.array("h", (src[int(i * 1.5)] for i in range(int(len(src) / 1.5))))
    pcm16 = out.tobytes()
    url = GW.replace("http", "ws") + "/v1/asr/ws?language=pt"
    partials = []
    async with websockets.connect(url, max_size=None) as ws:
        ready = json.loads(await ws.recv())
        print("ws ready:", ready.get("status"))
        if ready.get("status") != "ready":
            fail(f"no ready: {ready}")

        async def reader():
            async for m in ws:
                d = json.loads(m)
                if d.get("is_final"):
                    return d
                if d.get("text"):
                    partials.append(d["text"])

        task = asyncio.create_task(reader())
        step = 16000 * 2 // 50                       # 20 ms frames, real time
        for i in range(0, len(pcm16), step):
            await ws.send(pcm16[i:i + step])
            await asyncio.sleep(0.02)
        await ws.send(json.dumps({"action": "flush_eos"}))
        final = await asyncio.wait_for(task, 30)
    print(f"ws partials ({len(partials)}):", partials[-3:])
    print(f"ws final ({final.get('latency_ms')} ms): {final.get('text')!r}")
    if not final.get("text"):
        fail("empty final transcript")


if __name__ == "__main__":
    audio, r = main()
    asyncio.run(live(audio, r))
    print("OK")
