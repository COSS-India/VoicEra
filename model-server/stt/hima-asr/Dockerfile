# Hima-ASR (Prahaladha/hima-asr): HF Transformers, trust_remote_code.
#
# Same base as indic-conformer -- CUDA 13 runtime, torch from the cu130 index --
# so the layers are already cached on the GPU box. No NeMo, so this image does
# not reference the `nemo` build context.
FROM nvidia/cuda:13.0.1-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PORT=8001 \
    # Weights and the repo's modeling code come from the mounted folder that
    # fetch.sh filled at a pinned commit. Offline means a missing mount fails
    # fast instead of silently pulling whatever the repo holds today and
    # running its code with trust_remote_code.
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip libsndfile1 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages \
      torch torchaudio --index-url https://download.pytorch.org/whl/cu130 && \
    pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY server.py realtime_ws.py realtime_protocol.py ./
COPY static ./static

EXPOSE 8001
CMD ["python3", "server.py"]
