# Boiler IoT Simulation — Industry-Ready POC

A production-grade **Boiler IoT Proof of Concept** featuring:
- **Chronos AI** time-series forecasting with dual-mode simulation (Normal / Degradation)
- **Fine-tuned Gemini 2.5 Flash** Agentic RAG chatbot
- **Hybrid BM25 + ChromaDB + Cross-Encoder** knowledge retrieval
- **Redis** session-based chat history
- **Real-time alerts** with automatic recovery

---

## Architecture

```
EMQX (MQTT) → InfluxDB → Chronos Service (background thread)
                    ↓                        ↓
              FastAPI ←─────────── chronos_cache (30s refresh)
                 ↓
         Redis (chat history) + ChromaDB (knowledge base)
                 ↓
        Gemini 2.5 Flash (Vertex AI) — Agentic RAG
                 ↓
         Next.js Dashboard / REST API / WebSocket
```

---

## Quick Start — Step by Step

### Prerequisites
- Docker Desktop (latest)
- WSL2 backend (Windows)
- Python 3.11+
- Node.js 18+
- `uv` package manager (optional, for Python deps)

### 1 — Docker Setup

**Install Docker Desktop:**
```bash
# Windows: download from docker.com, run installer
# Enable WSL2 during install
```

**Pull required images:**
```bash
docker pull bitnami/redis:7
docker pull influxdb:2.7
docker pull grafana/grafana:10
docker pull emqx/emqx:5.8
```

**Start infrastructure:**
```bash
docker compose up -d
# Services: EMQX (MQTT) + InfluxDB + Grafana + Redis
```

**Verify services:**
```bash
docker ps
# Confirm all 4 containers show "Up"
```

**Access URLs:**
| Service   | Port  | URL                      |
|-----------|-------|--------------------------|
| EMQX UI   | 18083 | http://localhost:18083   |
| InfluxDB  | 8086  | http://localhost:8086    |
| Grafana   | 3000  | http://localhost:3000    |
| Redis     | 6379  | redis://localhost:6379   |

### 2 — Python Environment

**Create venv:**
```bash
python -m venv .venv
```

**Activate (Windows):**
```bash
.venv\Scripts\activate
```

**Install deps:**
```bash
pip install -r requirements.txt
# or with uv:
uv sync
```

### 3 — Run Simulators (4 Terminals)

**Terminal 1 — Boiler simulator:**
```bash
.venv\Scripts\activate
python publisher/simulators/boiler_simulator.py
```

**Terminal 2 — Chimney simulator:**
```bash
.venv\Scripts\activate
python publisher/simulators/chimney_simulator.py
```

**Terminal 3 — InfluxDB consumer:**
```bash
.venv\Scripts\activate
python consumers/influx_consumer.py
```

**Terminal 4 — Fault detector:**
```bash
.venv\Scripts\activate
python consumers/fault_detector.py
```

### 4 — Start Backend

**Terminal 5:**
```bash
.venv\Scripts\activate
uvicorn api.chatbot_api:app --reload --port 8000
```

**API docs:** http://localhost:8000/docs

### 5 — Optional UI Dashboard

```bash
npm install
npm run dev
# Opens at http://localhost:3000
```

### Shutdown
```bash
docker compose down
deactivate
```

---

## API Reference

### Chat (with Redis history)
```bash
# Non-streaming (returns full answer)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"Is the boiler temperature safe?","session_id":"demo"}'

# Streaming (SSE)
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"question":"Predict main steam temp for next 10 min","session_id":"demo"}'

# Clear session history
curl -X DELETE http://localhost:8000/chat/demo
```

### Simulation Mode
```bash
# Switch to Degradation mode (triggers Chronos alert pipeline)
curl -X POST http://localhost:8000/simulation/mode \
  -H "Content-Type: application/json" \
  -d '{"mode":"degradation"}'

# Switch back to Normal
curl -X POST http://localhost:8000/simulation/mode \
  -H "Content-Type: application/json" \
  -d '{"mode":"normal"}'

# Get current mode
curl http://localhost:8000/simulation/mode
```

### Chronos Forecast
```bash
# All sensors (sorted by urgency: critical → warning → normal)
curl http://localhost:8000/chronos/forecast

# Single sensor
curl "http://localhost:8000/chronos/forecast?sensor=main_steam_temp_boiler"
```

### Health Checks
```bash
curl http://localhost:8000/health           # Service health
curl http://localhost:8000/health/chronos   # Chronos cache status
curl http://localhost:8000/health/redis     # Redis memory + sessions
```

---

## Dual-Mode Simulation

| Mode | Behavior | Chronos Response |
|------|----------|-----------------|
| **Normal** | Sensors oscillate within SENSOR_NORMAL_RANGE. SAFE/WARNING cycle every 5 min. | `minutes_to_critical: null` — no breach projected |
| **Degradation** | `main_steam_temp_boiler` ramps +0.3°C/tick toward 582°C. `feedwater_temp` drops. | `minutes_to_critical ≤ 5` → fires CHRONOS_CRITICAL_FORECAST alert |

**Alert pipeline (Degradation mode):**
1. `alert_monitor_loop` checks `chronos_cache` every 15 seconds
2. Detects `minutes_to_critical ≤ 5` for any sensor
3. Writes `fault_events` to InfluxDB (tag: `source=chronos_auto_alert`)
4. Broadcasts JSON alert to all `/ws/alerts` WebSocket clients
5. **Auto-recovery**: resets `simulation_mode` → `"normal"` automatically

---

## Redis Chat Cache

Session history is stored in Redis per `session_id`:

```
chat:{session_id}         LIST   — up to 20 turns (LTRIM enforced)
chat:{session_id}:summary STRING — compressed prior context
chat:{session_id}:meta    HASH   — last_seen, turn_count
```

**TTL:** 24 hours (refreshed on every append)  
**Local dev:** `redis://localhost:6379/0` (Docker redis service)  
**Production:** Replace `REDIS_URL` in `.env` with Upstash free-tier URL:
```
REDIS_URL=rediss://default:<token>@<host>.upstash.io:6379
REDIS_TLS=true
```
Upstash free tier: 10,000 commands/day · 256MB · no credit card required.

---

## Hybrid RAG Retrieval

The knowledge tool uses a three-stage pipeline:
1. **ChromaDB** — dense semantic search (OpenAI `text-embedding-3-small`)
2. **BM25Okapi** — keyword search over the same corpus (fault codes, IBR references)
3. **CrossEncoder** (`ms-marco-MiniLM-L-6-v2`) — reranks merged candidates

Expected improvement: **+15–25% recall** on domain-specific fault-code queries.

---

## Chronos Evaluation

Run the full evaluation suite:
```bash
# Run all three evaluation buckets
python -m evaluation.chronos_eval --bucket all

# Generate presentation charts
python -m evaluation.plot_results
# Charts saved to evaluation/results/
```

Industry benchmarks:
| Bucket | Metric | Pass Threshold | Standard |
|--------|--------|---------------|---------|
| 6a | MAPE temp/pressure | < 15% | ISA-99 |
| 6a | MAPE emissions | < 25% | EPA EG-40 |
| 6b | Faults with ≥10 min lead | ≥ 70% | IEC 62443-4 |
| 6c | F1 anomaly detection | ≥ 0.6 | IEEE 1687 |

---

## Project Structure

```
Boiler-IOT-Simulation/
├── api/
│   └── chatbot_api.py          ← FastAPI (chat, simulation mode, alerts, health)
├── assistant/
│   ├── agent/
│   │   ├── alert_manager.py    ← ★ NEW: Chronos alert pipeline + auto-recovery
│   │   ├── chronos_service.py  ← Background Chronos refresh loop
│   │   ├── orchestrator.py     ← Gemini ReAct agent (now Redis-aware)
│   │   └── tools/
│   │       ├── chronos_tool.py
│   │       ├── knowledge_tool.py  ← ★ UPGRADED: Hybrid BM25 + reranker
│   │       ├── realtime_tool.py
│   │       ├── fault_history.py
│   │       └── predict_trend.py
│   ├── cache/
│   │   └── chat_cache.py       ← ★ NEW: Redis session chat history
│   ├── retrieval/
│   │   └── hybrid_retriever.py ← ★ NEW: BM25 + ChromaDB + cross-encoder
│   └── config.py               ← All settings (now includes Redis vars)
├── publisher/
│   └── simulators/
│       ├── boiler_simulator.py ← ★ UPGRADED: Dual-mode (Normal/Degradation)
│       └── chimney_simulator.py
├── consumers/
│   ├── influx_consumer.py
│   └── fault_detector.py
├── evaluation/
│   ├── chronos_eval.py         ← 3-bucket industry benchmark suite
│   └── plot_results.py         ← ★ NEW: Matplotlib charts for POC slides
├── knowledge_base/
│   └── indexer.py              ← ChromaDB ingestion
├── docker-compose.yml          ← ★ UPDATED: Added Redis service
├── requirements.txt            ← ★ UPDATED: redis, rank-bm25, sentence-transformers
└── .env                        ← ★ UPDATED: Redis config vars
```

---

## Environment Variables (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `REDIS_TLS` | `false` | Enable TLS (set `true` for Upstash) |
| `CHAT_HISTORY_MAX_TURNS` | `20` | Max messages per session |
| `CHAT_HISTORY_TTL_SECONDS` | `86400` | Session expiry (24h) |
| `CHRONOS_MODEL` | `amazon/chronos-t5-small` | Chronos model variant |
| `CHRONOS_DEVICE` | `cpu` | `cpu` or `cuda` |
| `CHRONOS_REFRESH_INTERVAL` | `30` | Cache refresh every N seconds |
| `FASTAPI_URL` | `http://localhost:8000` | Backend URL (used by simulator) |

---

## WebSocket Endpoints

### `/ws/chat`
Real-time chat (request-response per message):
```json
→ {"question": "Is the boiler safe?", "session_id": "demo"}
← {"answer": "...", "steps": [...], "latency_ms": 1230}
```

### `/ws/alerts`
Subscribe to Chronos degradation alerts:
```json
← {"type": "chronos_alert", "sensor": "main_steam_temp_boiler",
   "minutes_to_critical": 3.2, "anomaly_score": 0.91,
   "auto_recovery": true, "timestamp": "2026-06-23T07:30:00Z"}
← {"type": "heartbeat", "mode": "normal", "timestamp": "..."}
```
