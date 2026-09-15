# rumik-oss-1 — single-container serving image for the TTS slot.
#
# The base is a plain CPU Python image: the entire CUDA userspace arrives as pip
# wheels pulled in by torch. The host supplies only the NVIDIA driver, exposed at
# run time by nvidia-container-toolkit. That keeps this image portable across GPU
# generations — nothing here is compiled for one architecture.
#
# Unlike tts/orpheus this needs no compiler at run time: there is no vLLM and so
# no Triton kernels JIT-compiling on first use. libgomp1 is torch's; libsndfile1
# is what soundfile uses to encode the mp3/flac/opus response formats.
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/hf-cache

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libsndfile1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so app edits do not invalidate the (large) wheel layer.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copied so the image is self-contained and can be run without a checkout.
# At run time the slot bind-mounts ./tts/${TTS_MODEL} over /app, so these files
# come from the working tree instead — editing server.py needs a container
# restart, not a rebuild.
COPY *.py ./
COPY static ./static

# Non-root, and portable: this image does NOT need root. The MPS wrinkle that
# forces tts/orpheus to run as uid 0 — an MPS client must match the daemon's
# user, and on a root-owned daemon a uid-1000 CUDA init blocks in the handshake
# with no log line — is handled in this folder's compose.mps.yml, which
# compose-files.sh layers in only when a daemon is actually present. So a host
# with a Default-mode GPU keeps the unprivileged user.
#
# HF_HOME is /hf-cache and nothing else creates it, so it is created here with
# the right owner: a fresh named volume mounted over it then inherits that
# ownership from the image rather than arriving root-owned and unwritable.
RUN useradd -m -u 1000 rumik && \
    mkdir -p /hf-cache && \
    chown -R rumik:rumik /home/rumik /app /hf-cache
USER rumik

# The slot contract is one service on 8002, and PORT is how the slot says so.
# Read here rather than in config.py's own default, so there is exactly one knob
# for the port — see the note in config.py about RUMIK_PORT.
ENV PORT=8002
EXPOSE 8002
CMD ["sh", "-c", "exec python -m uvicorn server:app --host 0.0.0.0 --port ${PORT:-8002} --no-access-log"]
