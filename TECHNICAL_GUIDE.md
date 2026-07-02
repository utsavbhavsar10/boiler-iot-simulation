# 🏭 Boiler IoT Simulation — Technical & Developer Guide
### Welcoming You to the Boiler-AI Predict-and-Prevent Engineering Stack!
#### *Written by a Senior Engineer for our Junior Team Members*

Welcome to the team! If you are reading this, it means you've just inherited our Boiler IoT Simulation codebase. Don't worry—this isn't your average "hello world" dashboard. You are looking at an **industry-ready, predict-and-prevent AI IoT system**. 

Instead of waiting for a boiler to overheat and blow a valve (traditional reactive monitoring), our stack uses **probabilistic deep learning (Amazon Chronos)** to predict temperature breaches up to 20-30 minutes in advance. It integrates a **Gemini 2.5 Flash chatbot** backed by **Redis session storage** and **Hybrid Vector + BM25 retrieval** to help human operators debug faults. It even evaluates its own chatbot answers automatically using **Ragas** and writes quality scores straight to InfluxDB!

Let's walk through how this system fits together, how to spin it up, how to switch simulation modes, and how to run evaluations. Grab a coffee, and let's get you onboarded!

---

## 📋 Table of Contents
1. [System Architecture & Data Flow](#1-system-architecture--data-flow)
2. [What We Have Built & Applied (The Tech Stack)](#2-what-we-have-built--applied-the-tech-stack)
3. [Step-by-Step Project Startup Guide](#3-step-by-step-project-startup-guide)
4. [Simulation Modes: Switching & How They Work](#4-simulation-modes-switching--how-they-work)
5. [Evaluations (RAGAS & Chronos Prediction Accuracy)](#5-evaluations-ragas--chronos-prediction-accuracy)
6. [Redis Caching & Conversational Memory](#6-redis-caching--conversational-memory)
7. [Senior-to-Junior Troubleshooting & Architecture Tips](#7-senior-to-junior-troubleshooting--architecture-tips)

---

## 1. System Architecture & Data Flow

To understand the files you'll be editing, you first need to understand how data flows through the stack:

```
                                  [ DOCKER CONTAINER RUNTIME ]
                                 ┌────────────────────────────┐
                                 │  • EMQX (MQTT Broker)      │
                                 │  • InfluxDB (TS Database)  │
                                 │  • Redis (Session Cache)   │
                                 │  • Grafana (Dashboard)     │
                                 └──────────────┬─────────────┘
                                                │
       1. Publish Sensor Ticks                  │ 2. Consume & Store
   ┌──────────────────────────────┐             │
   │  boiler_simulator.py (MQTT)  ├─────────────┼─────────────┐
   │  chimney_simulator.py (MQTT) ├─────────────┤             ▼
   └──────────────────────────────┘             │     influx_consumer.py
                                                │     fault_detector.py
                                                │             │
                                                │             ▼
                                                │       [ InfluxDB ]
                                                │     (boiler_data bucket)
                                                │             │
   ┌────────────────────────────────────────────┘             │ 3. Fetch History (30s)
   │                                                          ▼
   │   ┌──────────────────────────────────────────────┐   ┌─────────────────────────┐
   │   │                FastAPI Backend               │◄──┤ Chronos Service         │
   │   │             (api/chatbot_api.py)             │   │ (amazon/chronos-t5)     │
   │   ├──────────────────────────────────────────────┤   └─────────────────────────┘
   │   │  • /chat & /chat/stream (SSE)                │
   │   │  • /simulation/mode (Switch Modes)           │
   │   │  • /chronos/forecast (Get prediction curves) │
   │   │  • /ws/alerts (WebSocket live alerts)        │
   │   └──────────────────────┬───────────────────────┘
   │                          │
   │   ┌──────────────────────┼───────────────────────┐
   │   ▼                      ▼                       ▼
   [ Redis Cache ]      [ ChromaDB ]          [ Vertex AI Gemini ]
(Chat Session History) (Knowledge Docs)      (Orchestrator LLM Agent)
                              │                       │
                              └───────────┬───────────┘
                                          │ 4. Answer Generation & Eval
                                          ▼
                                   [ Ragas Engine ] ──► Logs quality back to InfluxDB
                                  (evaluator.py)
```

---

## 2. What We Have Built & Applied (The Tech Stack)

Here is a summary of the core engineering pieces applied to this project to make it production-ready:

1. **Chronos AI Forecaster (`assistant/agent/chronos_service.py`)**:
   - Uses the `amazon/chronos-t5-small` model. This is a pre-trained time-series forecaster that treats numbers as tokens.
   - It runs on a background daemon thread (`chronos-refresh`), fetching the last 20 minutes of sensor data from InfluxDB every 30 seconds and running inference for all 25 system sensors.
   - It outputs: a median forecast, 10th and 90th confidence bands, expected minutes to Warning/Critical thresholds, and an anomaly score.

2. **Dual-Mode Simulator with Auto-Recovery (`publisher/simulators/boiler_simulator.py` & `assistant/agent/alert_manager.py`)**:
   - **Normal Mode**: Sensors oscillate safely inside normal operating bounds, occasionally hitting warnings on a scheduled phase to simulate typical minor drifts.
   - **Degradation Mode**: Manually triggered. The simulator slowly injects a thermal drift (+0.3°C per tick) on the main steam temperature.
   - **Alert Monitor**: A background thread polls the Chronos cache. If in Degradation mode and any sensor is predicted to breach its critical threshold within 5 minutes, it fires a `CHRONOS_CRITICAL_FORECAST` alert, writes it to InfluxDB, broadcasts it to connected WebSockets, and flips the simulation mode back to `normal` (auto-recovery).

3. **Hybrid RAG Retriever (`assistant/agent/tools/knowledge_tool.py`)**:
   - Combines semantic vector search (ChromaDB containing operations guides) with keyword search (BM25) using a Cross-Encoder reranker (`mixedbread-ai/mxbai-rerank-xlarge-v1`). This ensures when the operator asks how to fix a fault, they get exact instructions, not generic AI fluff.

4. **Redis Chat Caching (`assistant/cache/chat_cache.py`)**:
   - Saves tokens and keeps conversations context-aware. It stores session turns in local/cloud Redis. 
   - Uses list trimming to keep only the last 20 turns (`CHAT_HISTORY_MAX_TURNS`) and maintains a compressed summary of older turns when the conversation length grows.

5. **Auto-Evaluation with Ragas (`evaluation/evaluator.py`)**:
   - Monitors chatbot answer quality. Every time an API chat request finishes, Ragas runs in a background thread to score the answer on **Faithfulness** (relying on `gemini-2.5-pro` as judge) and **Answer Relevancy** (using OpenAI embeddings).
   - Writes scores to InfluxDB under `chatbot_evaluation` so they can be graphed in Grafana.

---

## 3. Step-by-Step Project Startup Guide

Since we are dealing with multiple distributed microservices (simulators, consumers, broker, databases, API backend), **startup order is critical**.

### Step 3.1: Start the Infrastructure (Docker)
First, make sure Docker Desktop is running on your machine. Open a terminal in the project root and start the infrastructure containers:
```bash
docker compose up -d
```
This launches:
* **EMQX** (Port `1883` for MQTT, `18083` for Web UI Dashboard) — Our message broker.
* **InfluxDB** (Port `8086`) — Where all sensor historical records are written.
* **Redis** (Port `6379`) — Handles our chatbot session memory cache.
* **Grafana** (Port `3000`) — Renders real-time dashboards of the boiler and system metrics.

> **Senior Tip**: Go to [http://localhost:18083](http://localhost:18083) (admin / public) to verify the MQTT broker is online. Visit [http://localhost:8086](http://localhost:8086) to make sure InfluxDB is accessible.

### Step 3.2: Verify Virtual Environment & Env Variables
We use `python 3.11+`. Check your [.env](file:///.env) file to ensure your API keys and GCP project details are configured:
```ini
GCP_PROJECT_ID=your-gcp-project-id
GCP_REGION=us-central1
OPENAI_API_KEY=sk-proj-YourOpenAIVectorKey...
INFLUX_URL=http://localhost:8086
INFLUX_TOKEN=my-super-secret-token-123
INFLUX_ORG=boiler_org
INFLUX_BUCKET=boiler_data
REDIS_URL=redis://localhost:6379/0
CHRONOS_MODEL=amazon/chronos-t5-small
CHRONOS_DEVICE=cpu
```

Make sure your virtual environment is active and dependencies are installed:
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Step 3.3: Launch the Services (The "5-Terminal" Startup)
Because this is a real-time simulation stack, you will need to open **5 separate terminal windows** (or use a terminal multiplexer like Tmux / VSCode split-panels). Run these in order:

#### Terminal 1: InfluxDB Consumer
This script subscribes to all sensor telemetry topics on EMQX and writes them to InfluxDB.
```bash
.venv\Scripts\activate
python consumers/influx_consumer.py
```

#### Terminal 2: Fault Detector
This consumer monitors the telemetry stream, compares values against static alert thresholds, and logs immediate faults to InfluxDB.
```bash
.venv\Scripts\activate
python consumers/fault_detector.py
```

#### Terminal 3: Boiler Simulator
Publishes temperature, pressure, flow, and oxygen level data to MQTT. It operates in Normal mode by default and polls the FastAPI backend for mode switches.
```bash
.venv\Scripts\activate
python publisher/simulators/boiler_simulator.py
```

#### Terminal 4: Chimney Simulator
Publishes opacity and emissions data (CO, CO2, SO2, NOx) to MQTT.
```bash
.venv\Scripts\activate
python publisher/simulators/chimney_simulator.py
```

#### Terminal 5: FastAPI Backend API & Chronos Service
This spins up the main API. During startup, it loads the Chronos time-series model into memory (takes ~10 seconds) and starts two daemon background threads (`chronos-refresh` and `alert-monitor`).
```bash
.venv\Scripts\activate
uvicorn api.chatbot_api:app --reload --port 8000
```

---

## 4. Simulation Modes: Switching & How They Work

Our system simulates a dual-mode behavior. As a junior developer, you need to understand how the background threads coordinate to handle a system emergency.

### 4.1 Normal Mode
* This is the default. The boiler simulator oscillates sensors within safe, normal limits. 
* Chronos will still forecast the future, but because there is no upward trend, the forecast's `minutes_to_critical` field will return `null` (no breach predicted).
* The chatbot's context block will indicate that all systems are green.

### 4.2 Degradation Mode
When switched to degradation mode:
1. The simulator starts ramping `main_steam_temp_boiler` by **+0.3°C per publish tick** (every 0.5s). It climbs from a baseline of ~540°C towards the critical limit of **565°C**.
2. Within **30 to 60 seconds**, Chronos sees this rising slope. The forecast starts showing `minutes_to_critical: 4.8` (or similar).
3. The `alert_monitor_loop` running inside the FastAPI process checks the cache every 15s. Once it detects `minutes_to_critical <= 5.0`:
   - It writes a critical `CHRONOS_CRITICAL_FORECAST` fault event to InfluxDB.
   - It broadcasts a live warning payload over WebSocket to any active frontend.
   - **Auto-Recovery**: It resets the simulation mode back to `"normal"`. This tells the simulator to stop ramping and cool back down, mimicking a control loop resolving the issue.
   - A **120-second cooldown** is enforced on the sensor to prevent duplicate alerts.

### 4.3 How to Switch Modes (API Calls)
You can switch the simulation mode using standard `curl` requests or REST client tools.

#### Switch to Degradation Mode:
```bash
curl -X POST http://localhost:8000/simulation/mode \
  -H "Content-Type: application/json" \
  -d '{"mode":"degradation"}'
```
*Expected response:* `{"ok":true,"mode":"degradation"}`

#### Switch to Normal Mode manually:
```bash
curl -X POST http://localhost:8000/simulation/mode \
  -H "Content-Type: application/json" \
  -d '{"mode":"normal"}'
```

#### Inspect current mode:
```bash
curl http://localhost:8000/simulation/mode
```
*Expected response:* `{"mode":"normal"}` (or `"degradation"`)

---

## 5. Evaluations (RAGAS & Chronos Prediction Accuracy)

We need concrete numbers to present to stakeholders proving our system is reliable. We evaluate two things: the chatbot answers (using Ragas) and the time-series forecasting (using custom InfluxDB testing).

### 5.1 RAGAS Chatbot Evaluation
Whenever you chat with the bot (either via `POST /chat` or the streaming `POST /chat/stream` SSE endpoint), the system evaluates the response quality asynchronously in a background thread.

#### Metrics Calculated:
1. **Faithfulness (0.0 - 1.0)**: Measures if the answer is factual and doesn't hallucinate. It uses `gemini-2.5-pro` to check the response against the retrieved documentation chunks.
2. **Answer Relevancy (0.0 - 1.0)**: Checks if the bot actually answered the user's specific query. It uses OpenAI embeddings to calculate semantic similarity.
3. **Tool Precision (0.0 - 1.0)**: Compares the tools the agent actually ran against a keyword-based set of expected tools. (e.g. asking for "real-time temp" should run `fetch_realtime_sensors`).

#### How to run the automated CLI test suite:
To run an offline evaluation against 5 baseline system questions, execute:
```bash
python test_ragas.py
```
This will print a beautiful terminal table:
```
================================================================──────────────────────────────────────────────
RAGAS SUMMARY
================================================================──────────────────────────────────────────────
#   Bug   Faith   Relev   ToolP   Overall  Steps  Lat(ms)   Q
--------------------------------------------------------------------------------------------------------------
1   no    1.000   0.941   1.000   0.965    1      1250      what is the current main steam flow?
2   no    1.000   0.892   1.000   0.938    1      1400      Is the boiler safe right now?
3   no    1.000   0.952   1.000   0.976    2      2100      Why does HIGH_FLUE_TEMP happen and how do I fix it?
4   no    1.000   0.880   1.000   0.931    1      1150      Will any sensor breach a threshold in the next 30 minutes?
5   no    1.000   0.910   1.000   0.944    1      1320      Have there been any faults in the last hour?
--------------------------------------------------------------------------------------------------------------
Mean faithfulness    : 1.000
Mean answer_relevancy: 0.915
Mean tool_precision  : 1.000
Bug fallback hits    : 0/5
================================================================──────────────────────────────────────────────
```
*Results will also be saved to [test_ragas_results.json](file:///e:/Boiler-IOT-Simulation/test_ragas_results.json).*

#### How to view Ragas metrics live:
Since all API chat calls log metrics directly to InfluxDB, you can query the `/metrics` endpoint to get 24-hour averages:
```bash
curl http://localhost:8000/metrics
```

---

### 5.2 Chronos Forecasting Evaluation
To prove the AI model can accurately predict faults before they happen, we run three evaluation benchmarks against InfluxDB historical data.

#### The 3 Evaluation Buckets:
* **Bucket 6a: Forecast Accuracy (MAPE)**
  - Holds out the last 20% of historical data, runs Chronos on the first 80%, and computes Mean Absolute Percentage Error (MAPE).
  - *Pass criteria*: MAPE < 15% for temperature/pressure, < 25% for emissions.
* **Bucket 6b: Fault Lead-Time**
  - Replays logged fault events and computes how far in advance Chronos forecasted `minutes_to_critical <= 5`.
  - *Pass criteria*: Median lead time >= 15 minutes, with >= 70% of faults detected at least 10 minutes ahead.
* **Bucket 6c: Anomaly Precision & Recall**
  - Labels windows leading up to faults as positive states and calculates the Precision, Recall, and F1-score of the Chronos anomaly detection.
  - *Pass criteria*: F1 >= 0.60.

#### Step 1: Run the evaluation suite
Ensure you have accumulated at least 20 minutes of sensor data in InfluxDB, then run:
```bash
python -m evaluation.chronos_eval --bucket all
```
This saves a baseline JSON file in `evaluation/results/chronos_baseline_{timestamp}.json`.

#### Step 2: Generate dark-mode validation charts
To compile these JSON results into slide-ready figures, run the plotting script:
```bash
python -m evaluation.plot_results
```
This reads the latest JSON report and exports three PNG charts into `evaluation/results/`:
1. `6a_mape_chart.png` — Horizontal bar chart displaying MAPE per sensor (colored green for pass, red for fail).
2. `6b_leadtime_chart.png` — Horizontal bar chart displaying fault prediction lead-time percentages.
3. `6c_anomaly_chart.png` — Grouped bar chart comparing F1, Precision, and Recall scores against the 0.6 pass line.

---

## 6. Redis Caching & Conversational Memory

Our chatbot uses Redis to keep conversation states light and cost-effective. Here is how session cache keys are structured:

* `chat:{session_id}` (Redis List): Holds raw JSON strings of the last 20 turns (`user` questions and `assistant` answers).
* `chat:{session_id}:summary` (Redis String): Stores a rolling text summary of older turns. If a chat reaches 20 turns (`CHAT_SUMMARY_THRESHOLD`), the orchestrator triggers an async task to summarize older entries, stores the summary here, and trims the raw list.
* `chat:{session_id}:meta` (Redis Hash): Stores session metadata (e.g. total tokens, active duration, tool counts).

### API Session Actions

#### Inspect Redis Health & Session Counts:
```bash
curl http://localhost:8000/health/redis
```
*Expected response:*
```json
{
  "status": "healthy",
  "total_sessions": 4,
  "memory_used_bytes": 1045000,
  "memory_peak_bytes": 1250000,
  "max_memory_policy": "allkeys-lru"
}
```

#### Clear a Chat Session (User presses "New Chat" in UI):
```bash
curl -X DELETE http://localhost:8000/chat/demo
```
*Expected response:* `{"ok":true,"session_id":"demo"}`

---

## 7. Senior-to-Junior Troubleshooting & Architecture Tips

Here are some tips to prevent common errors when running the system:

1. **"Chronos cache warming up..." / Why is `minutes_to_critical` null?**
   - The Chronos service needs a minimum of 10 data points in InfluxDB to compute forecasts. If you just wiped your database or started the simulators, wait **3 to 5 minutes** for InfluxDB to accumulate enough history before expecting forecasts to populate.

2. **Avoiding "Event loop is closed" errors in Ragas**
   - Ragas executes asynchronous tasks internally, which can conflict with FastAPI's request-response loop or ChatVertexAI's gRPC channel.
   - *How we fixed this*: In [evaluator.py](file:///e:/Boiler-IOT-Simulation/evaluation/evaluator.py#L43-L76), we route all RAGAS evaluation calls through a dedicated, single-threaded Executor (`_eval_executor`) bound to a persistent event loop (`_eval_loop`) with `nest_asyncio` applied. Never run raw `evaluate()` calls directly in FastAPI routes!

3. **GPU vs CPU for Chronos**
   - In [.env](file:///.env), `CHRONOS_DEVICE` is set to `"cpu"`. If your machine has a CUDA-compatible GPU, switch this value to `"cuda"`. This will decrease the 25-sensor forecast time from ~400ms down to ~80ms, saving CPU resources.

4. **Redis fallback support**
   - What happens if Docker's Redis container crashes? We've designed the code to fail gracefully. In [chat_cache.py](file:///e:/Boiler-IOT-Simulation/assistant/cache/__init__.py), if connection to Redis is lost, the agent logs a warning and automatically falls back to an in-memory dictionary. The user can still chat, but history won't persist across restarts.

5. **Vertex AI Credentials**
   - If Gemini is failing with authorization errors, make sure you have authenticated your local terminal with GCP:
     ```bash
     gcloud auth application-default login
     ```

Now you're fully equipped to work on this repository! If you make changes to the simulators or the forecasting service, make sure to run `python test_ragas.py` and `python -m evaluation.chronos_eval` to confirm that answer precision and forecast accuracy remain above threshold. 

Happy coding! 🚀
