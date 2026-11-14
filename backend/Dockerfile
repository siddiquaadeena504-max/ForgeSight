# CPU image by default. For GPU: build with --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu124
# and run with the NVIDIA container runtime (see docker-compose.gpu.yml).
FROM python:3.12-slim AS base
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 YOLO_CONFIG_DIR=/tmp/ultralytics
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install torch torchvision --index-url ${TORCH_INDEX} && pip install -r requirements.txt
COPY backend/ .
# trained models + pretrained backbone ship in the image (docker compose may still mount ./data over them)
COPY data/models /app/data/models
COPY data/weights /app/data/weights
RUN useradd -r -u 10001 forgesight && mkdir -p /app/data && chown -R forgesight /app
USER forgesight
ENV FS_MODELS_DIR=/app/data/models FS_STORAGE_DIR=/app/data/storage FS_WEIGHTS_DIR=/app/data/weights FS_ENV=production
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD curl -fsS http://localhost:8000/api/health || exit 1
# Migrations run on startup (alembic upgrade head). One worker: the job pool and model cache are per process;
# scale out with more replicas behind a load balancer, not more workers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
