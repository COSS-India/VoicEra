# Nemotron 9-language LID (frozen encoder + linear probe) plus Nemotron ASR
# for the detected language.
#
# Matches the validated LID stack (torch cu124 + NeMo 3.0).
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PORT=8004

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-dev build-essential ffmpeg libsndfile1 \
 && rm -rf /var/lib/apt/lists/* \
 && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app
COPY requirements.txt .
# Ubuntu 22.04's system pip is too old for --break-system-packages (24.04 slots use it).
RUN grep -vE '^(torch|torchaudio)' requirements.txt > /tmp/req.txt && \
    pip3 install --no-cache-dir \
      torch==2.6.0+cu124 torchaudio==2.6.0+cu124 \
      --index-url https://download.pytorch.org/whl/cu124 && \
    pip3 install --no-cache-dir -r /tmp/req.txt

COPY . .

EXPOSE 8004
CMD ["python3", "server.py"]
