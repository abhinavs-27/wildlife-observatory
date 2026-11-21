# Inference worker: SpeciesNet 5.0.6 (MegaDetector v5a + classifier + ensemble), CPU torch.
# Build on the Mac for the Pi:  docker buildx build --platform linux/arm64 -t observatory-worker .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy \
    KAGGLEHUB_CACHE=/models HF_HOME=/models/hf
# yolov5 imports OpenCV, which needs these shared libs even in headless mode.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /usr/local/bin/uv
WORKDIR /app
# CPU-only torch (avoids multi-GB CUDA wheels on amd64; arm64 wheels are CPU anyway).
RUN uv pip install --system --no-cache --index-url https://download.pytorch.org/whl/cpu \
    "torch>=2.0" "torchvision"
COPY pyproject.toml ./
COPY src ./src
RUN uv pip install --system --no-cache .
RUN useradd --create-home --uid 1000 observatory && mkdir -p /models && chown observatory /models
USER observatory
# Worker has no HTTP port; it is healthy while its process runs and it reaches the edge.
CMD ["observatory-worker"]
