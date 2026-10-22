# higgs-tts-3 adapter -- the TTS slot's container.
#
# Small on purpose: there is no model in this image. Higgs TTS 3 runs in the
# SGLang-Omni sidecar that compose.extra.yml brings (sidecar/Dockerfile); this
# image holds the OpenAI-contract adapter only -- voice roster, control tags,
# format encoding. libsndfile1 is what soundfile uses for mp3/flac/opus.
FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libsndfile1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copied so the image runs without a checkout. At run time the slot bind-mounts
# ./tts/${TTS_MODEL} over /app, so editing server.py needs a restart, not a
# rebuild -- and voices/ added later is picked up the same way.
COPY *.py ./
COPY voices ./voices

# Non-root: the adapter touches no GPU, so the MPS rule that forces sidecars to
# run as root (compose.mps.yml) never applies to it.
RUN useradd -m -u 1000 higgs && chown -R higgs:higgs /app
USER higgs

# PORT is how the slot says 8002; there is no HIGGS_PORT (see config.py).
ENV PORT=8002
EXPOSE 8002
CMD ["sh", "-c", "exec python -m uvicorn server:app --host 0.0.0.0 --port ${PORT:-8002} --no-access-log"]
