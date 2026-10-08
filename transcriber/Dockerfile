FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 \
    HF_HOME=/models/hf XDG_CACHE_HOME=/models/cache

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3-pip ffmpeg git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.11 /usr/bin/python

WORKDIR /app
COPY requirements.txt .
# Blackwell (sm_120) needs the CUDA 12.8 torch wheels.
RUN python -m pip install --no-cache-dir --upgrade pip \
 && python -m pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cu128 \
 && python -m pip install --no-cache-dir -r requirements.txt

COPY transcriber ./transcriber
COPY scripts ./scripts
ENTRYPOINT ["python", "-m", "transcriber.cli"]
