# pt-whisper: BuzzASR/portuguese (Whisper-large-v3 fine-tune) for the STT slot.
#
# Weights are NOT baked in. fetch.sh downloads them into ./models before the
# build, and the slot bind-mounts this folder at /app, so they appear at
# /app/models/portuguese at run time.
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libsndfile1 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Same CUDA wheel index as stt/indic-nemotron, which runs on this host's driver.
RUN pip install torch --index-url https://download.pytorch.org/whl/cu130

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY . /app

# Every variable server.py reads, with its default. compose.extra.yml overrides
# these from .env; tests/test_engine_env_surface.py checks the two agree.
ENV PORT=8001 \
    PTW_MODEL_DIR=/app/models/portuguese \
    PTW_MODEL_ID=pt-whisper \
    PTW_INTERIM_MS=600 \
    PTW_MAX_BUFFER_S=28 \
    PTW_VAD_THRESHOLD=0.5 \
    PTW_NUM_BEAMS=1 \
    PTW_CUDA_MEM_GB=0

EXPOSE 8001
CMD ["python", "server.py"]
