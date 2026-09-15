# rumik-oss-1 — single-container serving image for the TTS slot.
#
# The base is a plain CPU Python image: the entire CUDA userspace arrives as pip
# wheels pulled in by torch. The host supplies only the NVIDIA driver, exposed at
# run time by nvidia-container-toolkit. That keeps this image portable across GPU
# generations — nothing here is compiled for one architecture.
#
# gcc/g++ are needed at RUN TIME, not just build time: vLLM's Triton kernels
# JIT-compile on first use against the pip CUDA toolkit in site-packages.
# libgomp1 is torch's; libsndfile1 is what soundfile uses to encode the
# mp3/flac/opus response formats.
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/hf-cache \
    # flashinfer cannot JIT against CUDA 13 headers, so use vLLM's own sampler.
    # Harmless on older stacks; required on CUDA 13.
    VLLM_USE_FLASHINFER_SAMPLER=0

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ libgomp1 libsndfile1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so app edits do not invalidate the (large) wheel layer.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# vLLM's Triton kernels JIT against nvcc from the pip CUDA toolkit, so CUDA_HOME
# has to point at it. The build fails loudly if the expected layout is not there,
# rather than leaving a broken image to surface as a cryptic Triton error at the
# first request.
ENV CUDA_HOME=/usr/local/lib/python3.12/site-packages/nvidia/cu13
ENV PATH=$CUDA_HOME/bin:$PATH
RUN test -x "$CUDA_HOME/bin/nvcc" || { \
        echo "ERROR: nvcc not found under CUDA_HOME=$CUDA_HOME"; \
        echo "The pinned torch/vllm wheels moved their CUDA toolkit. Available:"; \
        ls -d /usr/local/lib/python3.12/site-packages/nvidia/*/bin 2>/dev/null || true; \
        exit 1; \
    }

# Copied so the image is self-contained and can be run without a checkout.
# At run time the slot bind-mounts ./tts/${TTS_MODEL} over /app, so these files
# come from the working tree instead — editing server.py needs a container
# restart, not a rebuild.
COPY *.py ./
COPY static ./static

# Installed, not merely copied, and this is the one thing here that a container
# restart cannot pick up. vLLM runs its EngineCore in a spawned process, so a
# model registration made in the server process never reaches the worker that
# loads the weights; entry points in the vllm.general_plugins group are loaded
# by every vLLM process instead. See rumik_vllm_plugin.py.
#
# --no-deps: the dependencies are already pinned in requirements.txt above, and
# resolving them again here would let pip move a version out from under them.
COPY pyproject.toml ./
RUN pip install --no-deps .

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
    mkdir -p /hf-cache /home/rumik/.triton && \
    chown -R rumik:rumik /home/rumik /app /hf-cache
USER rumik

# The slot contract is one service on 8002, and PORT is how the slot says so.
# Read here rather than in config.py's own default, so there is exactly one knob
# for the port — see the note in config.py about RUMIK_PORT.
ENV PORT=8002
EXPOSE 8002
CMD ["sh", "-c", "exec python -m uvicorn server:app --host 0.0.0.0 --port ${PORT:-8002} --no-access-log"]
