# pt-chatterbox: FearL0rd/Chatterbox-TTS-Portuguese for the TTS slot.
#
# Weights are NOT baked in. fetch.sh downloads them into ./checkpoints before
# the build, and the slot bind-mounts this folder at /app, so they appear at
# /app/checkpoints/portuguese at run time.
#
# Python 3.11: chatterbox-tts pins numpy<2 and torch==2.6.0 below 3.13.
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libsndfile1 ffmpeg ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY . /app

# Every variable server.py reads, with its default. compose.extra.yml overrides
# these from .env; tests/test_engine_env_surface.py checks the two agree.
ENV PORT=8002 \
    PTC_MODEL_DIR=/app/checkpoints/portuguese \
    PTC_MODEL_ID=pt-chatterbox \
    PTC_EXAGGERATION=0.5 \
    PTC_CFG_WEIGHT=0.5 \
    PTC_TEMPERATURE=0.8 \
    PTC_MAX_CHARS=300 \
    PTC_CUDA_MEM_GB=0

EXPOSE 8002
CMD ["python", "server.py"]
