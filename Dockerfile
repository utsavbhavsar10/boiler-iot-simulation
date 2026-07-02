# ══════════════════════════════════════════════════════════════════════════════
# Stage 1 — Python base
#   - Python 3.13 slim base
#   - Install system deps, copy source, install pip packages
#   - One image is shared by ALL python services (api, simulators, consumers)
# ══════════════════════════════════════════════════════════════════════════════
FROM python:3.13-slim AS python-base

# Prevent Python buffering + .pyc files in container
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System build deps needed by some packages (torch, chromadb, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    git \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first so Docker layer cache reuses this expensive step
COPY requirements.txt .

# Install CPU-only torch first (saves ~2GB vs default CUDA version)
RUN pip install --upgrade pip \
    && pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt

# Copy the entire project source
COPY . .

# ══════════════════════════════════════════════════════════════════════════════
# Stage 2 — FastAPI Backend (uvicorn)
# ══════════════════════════════════════════════════════════════════════════════
FROM python-base AS backend
EXPOSE 8000
CMD ["uvicorn", "api.chatbot_api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

# ══════════════════════════════════════════════════════════════════════════════
# Stage 3 — Boiler Simulator (publisher)
# ══════════════════════════════════════════════════════════════════════════════
FROM python-base AS boiler-simulator
CMD ["python", "publisher/simulators/boiler_simulator.py"]

# ══════════════════════════════════════════════════════════════════════════════
# Stage 4 — Chimney Simulator (publisher)
# ══════════════════════════════════════════════════════════════════════════════
FROM python-base AS chimney-simulator
CMD ["python", "publisher/simulators/chimney_simulator.py"]

# ══════════════════════════════════════════════════════════════════════════════
# Stage 5 — InfluxDB Consumer (writes MQTT → InfluxDB)
# ══════════════════════════════════════════════════════════════════════════════
FROM python-base AS influx-consumer
CMD ["python", "consumers/influx_consumer.py"]

# ══════════════════════════════════════════════════════════════════════════════
# Stage 6 — Fault Detector (consumer — raises fault alerts)
# ══════════════════════════════════════════════════════════════════════════════
FROM python-base AS fault-detector
CMD ["python", "consumers/fault_detector.py"]

# ══════════════════════════════════════════════════════════════════════════════
# Stage 7 — Next.js Frontend
# ══════════════════════════════════════════════════════════════════════════════
FROM node:20-slim AS frontend-builder
WORKDIR /app/Frontend
COPY Frontend/package*.json ./
RUN npm ci
COPY Frontend/ ./
RUN npm run build

FROM node:20-slim AS frontend
WORKDIR /app/Frontend
ENV NODE_ENV=production
COPY --from=frontend-builder /app/Frontend/.next ./.next
COPY --from=frontend-builder /app/Frontend/public ./public
COPY --from=frontend-builder /app/Frontend/package*.json ./
COPY --from=frontend-builder /app/Frontend/node_modules ./node_modules
EXPOSE 3000
CMD ["npm", "start"]
