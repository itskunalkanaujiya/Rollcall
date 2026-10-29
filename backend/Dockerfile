# Build context is the repo root (scripts/download_model.py lives outside backend/).
# docker build -f backend/Dockerfile .

# Stage 1: build the frontend into static files served by FastAPI (single origin - no
# separate frontend host, so the session cookie and the recognition WebSocket both stay same-site).
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first - this layer only rebuilds when requirements.txt changes.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir --timeout 120 --retries 10 -r backend/requirements.txt

# Model weights - ~300MB, rarely changes, cached independently of app code so
# ordinary code deploys don't re-download it.
COPY scripts/download_model.py scripts/download_model.py
RUN python scripts/download_model.py && rm -f /app/backend/data/insightface/buffalo_l.zip

# App code last - this is what changes on every deploy.
COPY backend/alembic backend/alembic
COPY backend/alembic.ini backend/alembic.ini
COPY backend/app backend/app
COPY --from=frontend-build /app/frontend/dist backend/static

WORKDIR /app/backend
ENV PYTHONUNBUFFERED=1 ENVIRONMENT=production LOAD_MODEL_ON_STARTUP=true

EXPOSE 8000
CMD ["/bin/sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
