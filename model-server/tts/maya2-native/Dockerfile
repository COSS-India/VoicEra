# maya2-native — single-container serving image for the TTS slot.
#
# A plain CPU Python image: the CUDA userspace arrives as pip wheels pulled in by
# torch (cu128), and the host supplies only the NVIDIA driver through
# nvidia-container-toolkit. Same approach as tts/rumik-oss-1.
#
# gcc is needed at RUN TIME: Triton JIT-compiles a small launcher with the host C
# compiler the first time the fused kernels run (upstream's fast backbone and
# depth decoder are Triton). git is needed at build time only, for the pinned
# upstream commit in requirements.txt. libsndfile1 backs soundfile's mp3/opus/
# flac encoders, which upstream's server uses for those response formats.
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    TOKENIZERS_PARALLELISM=false \
    HF_HOME=/hf-cache

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libc6-dev git libsndfile1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Upstream installs four top-level packages beside maya3 -- `tts`, `serve`,
# `scripts`, `configs` -- and its engine reads <site-packages>/configs at import.
# Fail the build here, with the reason, rather than at the first model load.
RUN python -c "import maya3.server, maya3.api, serve.fast_backbone, tts.model.load_s3; \
import maya3.engine as e; \
assert (e.ROOT / 'configs' / 's3_fresh_v1.yaml').is_file(), 'configs/ not installed beside maya3'"

# Copied so the image runs without a checkout. At run time the slot bind-mounts
# ./tts/maya2-native over /app, so editing server.py needs a restart, not a
# rebuild. This folder must never contain a directory named tts/, serve/,
# scripts/ or configs/: /app is first on sys.path and would shadow upstream's.
COPY *.py ./
COPY static ./static

# Non-root. compose.mps.yml (layered in only when an MPS daemon exists) switches
# to root, because an MPS client must match the daemon's user -- see that file.
RUN useradd -m -u 1000 maya && \
    mkdir -p /hf-cache /home/maya/.triton && \
    chown -R maya:maya /home/maya /app /hf-cache
USER maya

# The slot contract is one service on 8002, and PORT is how the slot says so.
ENV PORT=8002
EXPOSE 8002
CMD ["python", "server.py"]
