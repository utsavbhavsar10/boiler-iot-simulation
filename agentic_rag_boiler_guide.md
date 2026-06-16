# 🤖 Boiler & Chimney Agentic RAG — Complete Developer Guide
### Fine-Tuned Gemini 2.5 Flash + Agentic RAG + Real-Time InfluxDB + Evaluation
#### Written by: Senior Agentic RAG Developer → Junior Developer

---

> **Your starting point:**
> ✅ Fine-tuned Gemini 2.5 Flash on Vertex AI (94% accuracy, 500 Q&A pairs)
> ✅ Grafana dashboard running with live boiler/chimney charts
> ✅ InfluxDB storing all sensor data and fault events
> ✅ MQTT simulators publishing data every 500ms
> ✅ ChromaDB knowledge base indexed
>
> **What this document builds:**
> A production-grade Agentic RAG chatbot where your fine-tuned Gemini model
> autonomously decides which tools to call, fetches real-time sensor data,
> predicts faults before they happen, and gives actionable guidance.

---

## 📚 New Concepts — Senior Developer Explains to Junior

Before writing a single line of code, every concept must be crystal clear.
If you skip this section, the code will feel like magic. Read it once carefully.

---

### Concept 1: What is "Agentic" — the core idea

The word **Agent** means the LLM is not just answering — it is **acting**.

In a normal chatbot:
```
User question → LLM → Answer
(LLM is passive — just generates text)
```

In an Agentic system:
```
User question → LLM THINKS → LLM DECIDES what to do
                           → LLM CALLS a tool (function)
                           → Tool returns real data
                           → LLM THINKS again with new data
                           → LLM CALLS another tool if needed
                           → LLM synthesises final ANSWER
(LLM is active — reasons, plans, executes, adapts)
```

The LLM is the **brain**. Tools are the **hands**. The brain decides when to use the hands.

---

### Concept 2: Tools — what they are and why they matter

A **Tool** is just a Python function that the LLM is allowed to call.

You describe each tool to the LLM using a schema:
```
Tool name:        fetch_realtime_sensors
Description:      Fetches the latest sensor readings from the boiler
                  and chimney from the last 5 minutes
Parameters:       none required
Returns:          dict of sensor name → current value + status

Tool name:        search_knowledge_base
Description:      Searches the boiler/chimney fault knowledge base
                  for guides, causes, and fix instructions
Parameters:       query (string) — what to search for
Returns:          list of relevant document excerpts
```

When the user asks "Is pressure safe?", your fine-tuned Gemini reads these
descriptions and reasons: "I need current pressure to answer this — I should
call fetch_realtime_sensors."

**The LLM never sees your Python code — it only sees your tool descriptions.**
Write clear descriptions. A vague description = tool never gets called correctly.

---

### Concept 3: ReAct Loop — Reason + Act

The pattern your agent follows is called **ReAct** (Reasoning + Acting):

```
Thought:  "The user wants to know if the boiler is safe right now.
           I need current sensor readings."
Action:   fetch_realtime_sensors()
Result:   {temperature: 87.4°C, pressure: 18.2 bar [OUT OF RANGE], ...}

Thought:  "Pressure 18.2 bar is critical. I need the fix guide for HIGH_PRESSURE."
Action:   search_knowledge_base("HIGH_PRESSURE fault causes and fix")
Result:   "HIGH_PRESSURE: caused by blocked outlet or stuck relief valve..."

Thought:  "I also need recent fault history to give full context."
Action:   get_fault_history(minutes=60)
Result:   [{fault_code: HIGH_PRESSURE, time: 3 min ago, severity: CRITICAL}]

Thought:  "I now have everything I need. I can give a complete answer."
Final Answer: "⚠️ CRITICAL: Boiler pressure is 18.2 bar, 29% above the
              14 bar safety threshold. HIGH_PRESSURE fault was first
              detected 3 minutes ago. Immediate action required: ..."
```

Each Thought → Action → Result cycle is one **step** of the agent.
Your agent can run up to N steps (you set the limit) before giving a final answer.

---

### Concept 4: Why your fine-tuned model is better than base Gemini here

Base Gemini 2.5 Flash reads tool results and generates a generic answer.

Your **fine-tuned model** with 94% accuracy on boiler data:
- Knows that 18.2 bar is not just "high" — it is specifically a HIGH_PRESSURE fault
- Knows the exact severity hierarchy (CRITICAL vs WARNING)
- Knows that HIGH_PRESSURE + LOW_WATER simultaneously = double critical
- Structures answers like a boiler engineer: Diagnosis → Root Cause → Action → Prevention
- Uses correct units, terminology, and Indian boiler standards (IBR)

The fine-tuning gave it the **domain expertise**.
Agentic RAG gives it **real-time eyes**.
Together = a senior boiler engineer available 24/7.

---

### Concept 5: Function Calling vs LangChain Agents

There are two ways to build agents:

**Option A: Native Gemini Function Calling** (what we use)
- Gemini API has built-in support for tool/function calling
- You define tools as JSON schemas
- Gemini decides which function to call and with what arguments
- You execute the function and return the result
- Cleaner, faster, fewer dependencies, works with Vertex AI

**Option B: LangChain AgentExecutor**
- More abstraction, more components
- Harder to debug
- Adds complexity you don't need when Gemini natively supports function calling

We use **Option A — Native Gemini Function Calling**.
It is the production-grade approach for Vertex AI deployments.

---

---

## 🏗️ System Architecture — Full Detail

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    AGENTIC RAG SYSTEM                                   │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  USER INTERFACE (React or API client)                            │  │
│  │  User types: "Why is pressure high and how do I fix it?"         │  │
│  └────────────────────────────┬─────────────────────────────────────┘  │
│                               │ HTTP POST /chat                        │
│  ┌────────────────────────────▼─────────────────────────────────────┐  │
│  │  FastAPI — /chat endpoint                                        │  │
│  │  Receives question, passes to AgentOrchestrator                  │  │
│  └────────────────────────────┬─────────────────────────────────────┘  │
│                               │                                        │
│  ┌────────────────────────────▼─────────────────────────────────────┐  │
│  │  AgentOrchestrator (agent/orchestrator.py)                       │  │
│  │                                                                  │  │
│  │  Step 1: Send question + tool schemas to Gemini                  │  │
│  │  Step 2: Gemini returns tool_call request                        │  │
│  │  Step 3: Execute the tool (Python function)                      │  │
│  │  Step 4: Send tool result back to Gemini                         │  │
│  │  Step 5: Repeat until Gemini gives final text answer             │  │
│  │  Step 6: Return answer + all steps taken + latency               │  │
│  └──────┬──────────┬──────────────┬──────────────┬──────────────────┘  │
│         │          │              │              │                      │
│    ┌────▼───┐  ┌───▼────┐  ┌─────▼────┐  ┌─────▼──────┐              │
│    │Tool 1  │  │Tool 2  │  │Tool 3    │  │Tool 4      │              │
│    │fetch_  │  │search_ │  │get_fault │  │predict_    │              │
│    │realtime│  │knowled │  │_history()│  │trend()     │              │
│    │_sensor │  │ge_base │  │          │  │            │              │
│    │()      │  │()      │  │InfluxDB  │  │InfluxDB    │              │
│    │        │  │        │  │fault_    │  │time-range  │              │
│    │InfluxDB│  │Chroma  │  │events    │  │query       │              │
│    └────────┘  └────────┘  └──────────┘  └────────────┘              │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  EvaluationEngine (evaluation/evaluator.py)                      │  │
│  │  Faithfulness · Answer Relevancy · Tool Selection · Latency      │  │
│  │  Scores → InfluxDB → Grafana dashboard                           │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 📁 Final Project Structure

This sits inside the existing `Boiler-IOT-Simulation/` repo. The simulators
and consumers are already in place; the `assistant/` package is the new
Agentic RAG layer that we are building.

```
Boiler-IOT-Simulation/
│
├── publisher/
│   └── simulators/
│       ├── boiler_simulator.py     ← already exists (MQTT publisher, BOILER_001)
│       └── chimney_simulator.py    ← already exists (MQTT publisher, CHIMNEY_001)
│
├── consumers/                       ← already exists
│   ├── influx_consumer.py           ← writes MQTT → InfluxDB
│   └── fault_detector.py            ← writes fault_events → InfluxDB
│
├── assistant/                       ← Agentic RAG lives here
│   ├── __init__.py
│   ├── config.py                   ← single source of truth (this file)
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── orchestrator.py         ← CORE: ReAct loop, tool execution
│   │   ├── tool_schemas.py         ← Tool descriptions sent to Gemini
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── realtime_tool.py    ← Tool 1: fetch live InfluxDB sensors
│   │       ├── knowledge_tool.py   ← Tool 2: search ChromaDB
│   │       ├── fault_tool.py       ← Tool 3: get fault history
│   │       └── prediction_tool.py  ← Tool 4: trend prediction
│   ├── evaluation/
│   │   └── evaluator.py            ← RAGAS metrics + InfluxDB logging
│   ├── api/
│   │   └── chatbot_api.py          ← FastAPI endpoints
│   └── knowledge_base/
│       ├── boiler_guides.py        ← domain documents
│       └── indexer.py              ← ChromaDB indexer
│
├── docker-compose.yml               ← MQTT broker, InfluxDB, Grafana
├── .env                             ← GCP_PROJECT_ID, INFLUX_TOKEN, etc.
└── requirements.txt
```

---

---

# PART 1 — CONFIGURATION (Single Source of Truth)

**Senior developer rule:** Never hardcode credentials or settings inside files.
All config goes in one place. Every other file imports from here.

Open `assistant/config.py` and extend it as follows. The env-var names
(`GCP_PROJECT_ID`, `GCP_REGION`, `TUNED_MODEL_ENDPOINT_v4`, …) match the
`.env` keys already used in this repo.

```python
"""
assistant/config.py — All configuration for the Boiler Agentic RAG system.
Every other file imports from here. Never hardcode values elsewhere.
"""

import os
from dotenv import load_dotenv
load_dotenv()

# ── Vertex AI (your fine-tuned Gemini 2.5 Flash) ──────────────────────
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GCP_REGION     = os.getenv("GCP_REGION", "us-central1")

# Your fine-tuned model endpoint from Vertex AI Model Registry
# Vertex AI → Online Prediction → Endpoints → copy the Endpoint resource name
FINE_TUNED_MODEL_ENDPOINT = os.getenv("TUNED_MODEL_ENDPOINT_v4")

# Model generation settings
GEMINI_TEMPERATURE = 0.1    # low = factual answers, not creative
GEMINI_MAX_TOKENS  = 1024
GEMINI_TOP_P       = 0.8

# Agent settings
MAX_AGENT_STEPS = 6         # max tool calls per query (prevents infinite loops)

# ── InfluxDB ───────────────────────────────────────────────────────────
INFLUX_URL    = os.getenv("INFLUX_URL",    "http://localhost:8086")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN",  "my-super-secret-token-123")
INFLUX_ORG    = os.getenv("INFLUX_ORG",    "boiler_org")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "boiler_data")

# ── ChromaDB ───────────────────────────────────────────────────────────
CHROMA_PATH       = os.getenv("CHROMA_PATH", "./chroma_db")
CHROMA_COLLECTION = "boiler-knowledge"
EMBEDDING_MODEL   = "all-MiniLM-L6-v2"   # free, 22MB, local
TOP_K_DOCS        = 3                     # how many docs to retrieve per query

# ── Sensor metadata ────────────────────────────────────────────────────
# These MUST match the sensors published by publisher/simulators/
# boiler_simulator.py and chimney_simulator.py.
SENSOR_UNITS = {
    # Boiler side (device_id: BOILER_001, MQTT prefix: boiler/)
    "main_steam_flow":             "t/h",
    "main_steam_temp_boiler":      "°C",
    "main_steam_pressure_boiler":  "MPa",
    "reheat_steam_temp_boiler":    "°C",
    "superheater_desup_flow":      "t/h",
    "reheater_desup_flow":         "t/h",
    "feedwater_temp":              "°C",
    "feedwater_flow":              "t/h",
    "feedwater_pressure":          "MPa",
    "flue_gas_temp":               "°C",
    "oxygen_level":                "%",

    # Turbine side (device_id: BOILER_001, MQTT prefix: turbine/)
    "main_steam_temp_turbine":     "°C",
    "main_steam_pressure_turbine": "MPa",
    "reheat_steam_temp_turbine":   "°C",
    "reheat_steam_pressure_turbine": "MPa",
    "control_stage_pressure":      "MPa",
    "high_exhaust_pressure":       "MPa",
    "condenser_vacuum":            "kPa",
    "circ_water_outlet_temp":      "°C",

    # Chimney side (device_id: CHIMNEY_001, MQTT prefix: chimney/)
    "flue_temp":                   "°C",
    "co2":                         "%",
    "o2":                          "%",
    "co":                          "ppm",
    "draft":                       "Pa",
    "stack_velocity":              "m/s",
}

# (low, high) = normal operating band. Outside this band but inside the
# critical band = WARNING. Outside the critical band = CRITICAL.
# Values lifted directly from the simulators' NORMAL dict.
SENSOR_NORMAL_RANGE = {
    # Boiler
    "main_steam_flow":              (800,   1000),
    "main_steam_temp_boiler":       (535,   545),
    "main_steam_pressure_boiler":   (16.0,  17.5),
    "reheat_steam_temp_boiler":     (535,   545),
    "superheater_desup_flow":       (10,    40),
    "reheater_desup_flow":          (0,     15),
    "feedwater_temp":               (270,   285),
    "feedwater_flow":               (800,   1000),
    "feedwater_pressure":           (18.0,  20.0),
    "flue_gas_temp":                (120,   140),
    "oxygen_level":                 (3,     5),

    # Turbine
    "main_steam_temp_turbine":      (530,   540),
    "main_steam_pressure_turbine":  (15.5,  17.0),
    "reheat_steam_temp_turbine":    (530,   540),
    "reheat_steam_pressure_turbine":(3.0,   4.0),
    "control_stage_pressure":       (10.0,  13.0),
    "high_exhaust_pressure":        (3.0,   4.0),
    "condenser_vacuum":             (4.0,   7.0),
    "circ_water_outlet_temp":       (25,    35),

    # Chimney  (note: draft is negative — closer to 0 = worse)
    "flue_temp":                    (150,   250),
    "co2":                          (8,     14),
    "o2":                           (3,     8),
    "co":                           (0,     50),
    "draft":                        (-5,    -2),
    "stack_velocity":               (3,     8),
}

# Critical alarm bands (outside these = CRITICAL severity).
# Mirrors crit_low/crit_high from the simulators so the agent can
# distinguish CRITICAL from WARNING.
SENSOR_CRITICAL_RANGE = {
    "main_steam_flow":              (700,   1100),
    "main_steam_temp_boiler":       (520,   565),
    "main_steam_pressure_boiler":   (15.0,  18.5),
    "reheat_steam_temp_boiler":     (520,   565),
    "superheater_desup_flow":       (0,     70),
    "reheater_desup_flow":          (0,     35),
    "feedwater_temp":               (250,   305),
    "feedwater_flow":               (700,   1100),
    "feedwater_pressure":           (16.0,  22.0),
    "flue_gas_temp":                (100,   175),
    "oxygen_level":                 (1.5,   8),
    "main_steam_temp_turbine":      (515,   560),
    "main_steam_pressure_turbine":  (14.5,  18.0),
    "reheat_steam_temp_turbine":    (515,   560),
    "reheat_steam_pressure_turbine":(2.5,   4.5),
    "control_stage_pressure":       (8.0,   15.0),
    "high_exhaust_pressure":        (2.5,   4.5),
    "condenser_vacuum":             (2.0,   13.0),
    "circ_water_outlet_temp":       (15,    42),
    "flue_temp":                    (100,   300),
    "co2":                          (5,     18),
    "o2":                           (1.5,   12),
    "co":                           (0,     150),
    "draft":                        (-9,    -0.5),
    "stack_velocity":               (1,     12),
}

# Logical grouping used by the tools. `device` matches the device_id
# sent in the MQTT payload. `measurement` is the InfluxDB measurement
# that the consumer writes these sensors into.
SENSOR_MEASUREMENTS = {
    "boiler_sensors": {
        "device": "BOILER_001",
        "measurement": "boiler_sensors",
        "sensors": [
            "main_steam_flow",
            "main_steam_temp_boiler",
            "main_steam_pressure_boiler",
            "reheat_steam_temp_boiler",
            "superheater_desup_flow",
            "reheater_desup_flow",
            "feedwater_temp",
            "feedwater_flow",
            "feedwater_pressure",
            "flue_gas_temp",
            "oxygen_level",
        ],
    },
    "turbine_sensors": {
        "device": "BOILER_001",
        "measurement": "turbine_sensors",
        "sensors": [
            "main_steam_temp_turbine",
            "main_steam_pressure_turbine",
            "reheat_steam_temp_turbine",
            "reheat_steam_pressure_turbine",
            "control_stage_pressure",
            "high_exhaust_pressure",
            "condenser_vacuum",
            "circ_water_outlet_temp",
        ],
    },
    "chimney_sensors": {
        "device": "CHIMNEY_001",
        "measurement": "chimney_sensors",
        "sensors": [
            "flue_temp",
            "co2",
            "o2",
            "co",
            "draft",
            "stack_velocity",
        ],
    },
}

# Fault codes raised by the simulators (publisher/simulators/*).
# Keep this in sync with FAULT_TYPES (boiler_simulator.py) and
# CHIMNEY_FAULTS (chimney_simulator.py).
FAULT_CATALOG = {
    # Boiler / turbine
    "HIGH_MAIN_STEAM_PRESSURE": {"sensor": "main_steam_pressure_boiler", "severity": "CRITICAL"},
    "LOW_FEEDWATER_FLOW":       {"sensor": "feedwater_flow",             "severity": "CRITICAL"},
    "LOW_FEEDWATER_PRESSURE":   {"sensor": "feedwater_pressure",         "severity": "CRITICAL"},
    "HIGH_FLUE_GAS_TEMP":       {"sensor": "flue_gas_temp",              "severity": "WARNING"},
    "LOW_OXYGEN":               {"sensor": "oxygen_level",               "severity": "WARNING"},
    "HIGH_OXYGEN":              {"sensor": "oxygen_level",               "severity": "WARNING"},
    "HIGH_REHEAT_TEMP":         {"sensor": "reheat_steam_temp_boiler",   "severity": "WARNING"},
    "CONDENSER_VACUUM_LOSS":    {"sensor": "condenser_vacuum",           "severity": "CRITICAL"},
    "HIGH_CIRC_WATER_TEMP":     {"sensor": "circ_water_outlet_temp",     "severity": "WARNING"},
    "EXCESSIVE_DESUP_SPRAY":    {"sensor": "superheater_desup_flow",     "severity": "WARNING"},
    # Chimney
    "BLOCKED_FLUE":             {"sensor": "draft",     "severity": "CRITICAL"},
    "HIGH_CO":                  {"sensor": "co",        "severity": "CRITICAL"},
    "LOW_DRAFT":                {"sensor": "draft",     "severity": "WARNING"},
    "HIGH_FLUE_TEMP":           {"sensor": "flue_temp", "severity": "WARNING"},
}
```

---

---

# PART 2 — THE FOUR TOOLS

Each tool is a Python file in `agent/tools/`.
Each file has exactly one public function that returns clean, structured data.

**Senior developer rule:** Tools must be:
1. **Fast** — under 500ms each. LLM waits while tool runs.
2. **Reliable** — always return something, never crash. Use try/except everywhere.
3. **Descriptive** — return human-readable strings the LLM can read directly.

---

## Tool 1 — fetch_realtime_sensors

Create `agent/tools/realtime_tool.py`:

```python
"""
Tool 1: fetch_realtime_sensors
Fetches the latest value for every boiler and chimney sensor
from InfluxDB. Returns a formatted string the LLM reads directly.
"""

from influxdb_client import InfluxDBClient
import sys
sys.path.append("../..")
from config import (
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    SENSOR_MEASUREMENTS, SENSOR_UNITS, SENSOR_NORMAL_RANGE
)

# Create one client, reuse it (don't reconnect every call)
_client    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
_query_api = _client.query_api()


def fetch_realtime_sensors() -> str:
    """
    Queries InfluxDB for the most recent value of every sensor.
    Returns a formatted string showing current readings with
    NORMAL/OUT_OF_RANGE status for each sensor.

    Called by the agent when it needs to know current sensor state.
    """
    results = {}

    for measurement, config in SENSOR_MEASUREMENTS.items():
        device  = config["device"]
        sensors = config["sensors"]

        for sensor in sensors:
            query = f"""
            from(bucket: "{INFLUX_BUCKET}")
              |> range(start: -5m)
              |> filter(fn: (r) => r["_measurement"] == "{measurement}")
              |> filter(fn: (r) => r["sensor"] == "{sensor}")
              |> filter(fn: (r) => r["_field"] == "value")
              |> last()
            """
            try:
                tables = _query_api.query(query)
                for table in tables:
                    for record in table.records:
                        results[sensor] = {
                            "value":  round(record.get_value(), 2),
                            "device": device,
                            "time":   str(record.get_time()),
                        }
            except Exception as e:
                results[sensor] = {"error": str(e)}

    if not results:
        return "ERROR: Could not fetch sensor data from InfluxDB. Check if simulator is running."

    # ── Format as readable string for LLM ─────────────────────────
    lines = [
        "=== REAL-TIME SENSOR READINGS ===",
        f"Timestamp: latest values from last 5 minutes\n",
        "BOILER SENSORS (BOILER_001):",
    ]

    boiler_sensors  = SENSOR_MEASUREMENTS["boiler_sensors"]["sensors"]
    chimney_sensors = SENSOR_MEASUREMENTS["chimney_sensors"]["sensors"]

    out_of_range = []

    for sensor in boiler_sensors:
        if sensor not in results:
            lines.append(f"  {sensor:20s}: NO DATA")
            continue
        data = results[sensor]
        if "error" in data:
            lines.append(f"  {sensor:20s}: ERROR — {data['error']}")
            continue

        val  = data["value"]
        unit = SENSOR_UNITS.get(sensor, "")
        rng  = SENSOR_NORMAL_RANGE.get(sensor)
        if rng:
            lo, hi = rng
            status = "NORMAL" if lo <= val <= hi else "⚠️ OUT_OF_RANGE"
            if lo > val or val > hi:
                out_of_range.append(f"{sensor}={val}{unit} (normal: {lo}-{hi})")
        else:
            status = ""
        lines.append(f"  {sensor:20s}: {val:8.2f} {unit:6s}  [{status}]")

    lines.append("\nCHIMNEY SENSORS (CHIMNEY_001):")
    for sensor in chimney_sensors:
        if sensor not in results:
            lines.append(f"  {sensor:20s}: NO DATA")
            continue
        data = results[sensor]
        if "error" in data:
            lines.append(f"  {sensor:20s}: ERROR — {data['error']}")
            continue

        val  = data["value"]
        unit = SENSOR_UNITS.get(sensor, "")
        rng  = SENSOR_NORMAL_RANGE.get(sensor)
        if rng:
            lo, hi = rng
            status = "NORMAL" if lo <= val <= hi else "⚠️ OUT_OF_RANGE"
            if lo > val or val > hi:
                out_of_range.append(f"{sensor}={val}{unit} (normal: {lo}-{hi})")
        else:
            status = ""
        lines.append(f"  {sensor:20s}: {val:8.2f} {unit:6s}  [{status}]")

    if out_of_range:
        lines.append(f"\n⚠️  SENSORS OUT OF RANGE: {', '.join(out_of_range)}")
    else:
        lines.append("\n✅ All sensors within normal operating range")

    return "\n".join(lines)
```

---

## Tool 2 — search_knowledge_base

Create `agent/tools/knowledge_tool.py`:

```python
"""
Tool 2: search_knowledge_base
Searches the ChromaDB vector store for fault guides,
sensor interpretation docs, and diagnostic procedures.
"""

import chromadb
from chromadb.utils import embedding_functions
import sys
sys.path.append("../..")
from config import CHROMA_PATH, CHROMA_COLLECTION, EMBEDDING_MODEL, TOP_K_DOCS

# Initialise once, reuse
_embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBEDDING_MODEL
)
_chroma    = chromadb.PersistentClient(path=CHROMA_PATH)

try:
    _collection = _chroma.get_collection(
        name=CHROMA_COLLECTION,
        embedding_function=_embed_fn
    )
    print(f"✅ Knowledge base loaded: {_collection.count()} documents")
except Exception as e:
    print(f"❌ ChromaDB not found: {e}. Run knowledge_base/indexer.py first.")
    _collection = None


def search_knowledge_base(query: str) -> str:
    """
    Searches the boiler/chimney knowledge base for documents
    relevant to the given query.

    Use this tool when you need:
    - Fault explanations (causes, fixes, prevention)
    - Sensor interpretation guides
    - Safety thresholds and operating procedures
    - Multi-sensor diagnostic guides

    Args:
        query: Natural language search query.
               Examples: "HIGH_PRESSURE fault causes",
                         "how to interpret CO2 percentage",
                         "water level dropping diagnosis"

    Returns:
        String containing the most relevant knowledge base excerpts.
    """
    if _collection is None:
        return "ERROR: Knowledge base not initialised. Run knowledge_base/indexer.py."

    if not query or len(query.strip()) < 3:
        return "ERROR: Query too short. Provide a meaningful search term."

    try:
        results = _collection.query(
            query_texts=[query],
            n_results=min(TOP_K_DOCS, _collection.count()),
        )

        docs      = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]

        if not docs:
            return f"No relevant documents found for query: '{query}'"

        # ── Format results for LLM ────────────────────────────────
        sections = [f"=== KNOWLEDGE BASE RESULTS FOR: '{query}' ===\n"]

        for i, (doc, meta, dist) in enumerate(zip(docs, metadatas, distances)):
            relevance = round((1 - dist) * 100, 1)  # convert distance to %
            sections.append(
                f"[Document {i+1}] {meta.get('title', 'Unknown')} "
                f"(Relevance: {relevance}%)\n"
                f"{doc.strip()}\n"
            )

        return "\n---\n".join(sections)

    except Exception as e:
        return f"ERROR searching knowledge base: {e}"
```

---

## Tool 3 — get_fault_history

Create `agent/tools/fault_tool.py`:

```python
"""
Tool 3: get_fault_history
Retrieves recent fault events from InfluxDB fault_events measurement.
"""

from influxdb_client import InfluxDBClient
from datetime import datetime
import sys
sys.path.append("../..")
from config import INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET


_client    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
_query_api = _client.query_api()


def get_fault_history(minutes: int = 60) -> str:
    """
    Retrieves fault events that occurred in the last N minutes
    from the boiler and chimney monitoring system.

    Use this tool when you need to:
    - Know what faults have occurred recently
    - Understand fault frequency and patterns
    - Check if a current reading is part of an ongoing fault
    - Give historical context in your answer

    Args:
        minutes: How many minutes of history to fetch (default: 60).
                 Use 30 for recent faults, 1440 for last 24 hours.

    Returns:
        String listing fault events with severity, sensor, and timestamp.
    """
    query = f"""
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -{minutes}m)
      |> filter(fn: (r) => r["_measurement"] == "fault_events")
      |> filter(fn: (r) => r["_field"] == "message")
      |> sort(columns: ["_time"], desc: true)
      |> limit(n: 20)
    """

    try:
        tables = _query_api.query(query)
        faults = []

        for table in tables:
            for record in table.records:
                faults.append({
                    "time":       str(record.get_time()),
                    "fault_code": record.values.get("fault_code", "UNKNOWN"),
                    "severity":   record.values.get("severity", "UNKNOWN"),
                    "sensor":     record.values.get("sensor", ""),
                    "message":    record.get_value(),
                })

        if not faults:
            return f"✅ No fault events in the last {minutes} minutes. System operating normally."

        # ── Count severity ─────────────────────────────────────────
        critical_count = sum(1 for f in faults if f["severity"] == "CRITICAL")
        warning_count  = sum(1 for f in faults if f["severity"] == "WARNING")

        lines = [
            f"=== FAULT HISTORY (last {minutes} minutes) ===",
            f"Total events: {len(faults)} "
            f"| Critical: {critical_count} | Warning: {warning_count}\n",
        ]

        for f in faults:
            emoji = "🚨" if f["severity"] == "CRITICAL" else "⚠️ "
            lines.append(
                f"{emoji} [{f['severity']:8s}] {f['fault_code']:25s} "
                f"| sensor: {f['sensor']:20s} | {f['time']}"
            )
            # Add message detail for most recent 5
            if len(lines) <= 8:
                lines.append(f"   ↳ {f['message']}")

        return "\n".join(lines)

    except Exception as e:
        return f"ERROR fetching fault history: {e}"
```

---

## Tool 4 — predict_trend

Create `agent/tools/prediction_tool.py`:

```python
"""
Tool 4: predict_trend
Fetches sensor values over a time window, calculates trend,
and predicts when the sensor will reach a critical threshold.
This is the "prediction" capability of your agent.
"""

from influxdb_client import InfluxDBClient
import sys
sys.path.append("../..")
from config import (
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    SENSOR_NORMAL_RANGE, SENSOR_UNITS, SENSOR_MEASUREMENTS,
)

_client    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
_query_api = _client.query_api()


def predict_trend(sensor_name: str, window_minutes: int = 30) -> str:
    """
    Analyses the trend of a sensor over the last N minutes and predicts
    whether it will reach a dangerous threshold, and when.

    Use this tool when:
    - A sensor is changing over time and you need to predict future risk
    - User asks "will pressure reach critical level?", "how long before fault?"
    - You want to give a proactive warning before a fault occurs

    Args:
        sensor_name:    Name of the sensor (e.g., "pressure", "temperature",
                        "water_level", "co", "flue_temp")
        window_minutes: How many minutes of history to analyse (default: 30)

    Returns:
        String with trend analysis, rate of change, and time-to-threshold prediction.
    """

    # Determine which measurement table to query by looking up the
    # sensor in SENSOR_MEASUREMENTS (boiler_sensors / turbine_sensors /
    # chimney_sensors). Defaults to boiler_sensors if unknown.
    measurement = "boiler_sensors"
    for group, cfg in SENSOR_MEASUREMENTS.items():
        if sensor_name in cfg["sensors"]:
            measurement = cfg["measurement"]
            break

    query = f"""
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -{window_minutes}m)
      |> filter(fn: (r) => r["_measurement"] == "{measurement}")
      |> filter(fn: (r) => r["sensor"] == "{sensor_name}")
      |> filter(fn: (r) => r["_field"] == "value")
      |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
    """

    try:
        tables  = _query_api.query(query)
        points  = []

        for table in tables:
            for record in table.records:
                points.append({
                    "time":  record.get_time(),
                    "value": round(record.get_value(), 3),
                })

        if len(points) < 3:
            return (
                f"Insufficient data for trend analysis on '{sensor_name}'. "
                f"Need at least 3 minutes of data. Only {len(points)} points found."
            )

        # ── Calculate trend (simple linear regression slope) ──────
        n      = len(points)
        values = [p["value"] for p in points]

        # Slope = (n*Σxy - Σx*Σy) / (n*Σx² - (Σx)²)
        # x = index (time step), y = sensor value
        sum_x  = sum(range(n))
        sum_y  = sum(values)
        sum_xy = sum(i * v for i, v in enumerate(values))
        sum_xx = sum(i * i for i in range(n))

        denominator = n * sum_xx - sum_x ** 2
        if denominator == 0:
            slope = 0.0
        else:
            slope = (n * sum_xy - sum_x * sum_y) / denominator

        # Slope is per time step (1 minute) → change per minute
        rate_per_minute = round(slope, 4)

        current_value = values[-1]
        unit          = SENSOR_UNITS.get(sensor_name, "")

        # ── Determine direction and risk ───────────────────────────
        normal = SENSOR_NORMAL_RANGE.get(sensor_name)
        lines  = [
            f"=== TREND ANALYSIS: {sensor_name.upper()} ===",
            f"Window:          Last {window_minutes} minutes ({n} data points)",
            f"Current value:   {current_value} {unit}",
            f"First value:     {values[0]} {unit}",
            f"Rate of change:  {rate_per_minute:+.4f} {unit}/minute",
        ]

        if normal:
            lo, hi = normal
            lines.append(f"Normal range:    {lo} to {hi} {unit}")

            # Is it currently in range?
            in_range = lo <= current_value <= hi
            lines.append(f"Current status:  {'✅ NORMAL' if in_range else '⚠️ OUT OF RANGE'}")

            # Predict time to threshold
            if rate_per_minute > 0 and current_value < hi:
                # Rising trend — when will it hit the upper threshold?
                minutes_to_upper = (hi - current_value) / rate_per_minute
                if minutes_to_upper <= 60:
                    lines.append(
                        f"\n⚠️  PREDICTION: At current rate, {sensor_name} will reach "
                        f"the upper threshold of {hi} {unit} in "
                        f"{minutes_to_upper:.1f} minutes."
                    )
                else:
                    lines.append(
                        f"\n✅ PREDICTION: At current rate, {sensor_name} will reach "
                        f"upper threshold in {minutes_to_upper:.1f} minutes — "
                        f"no immediate concern."
                    )

            elif rate_per_minute < 0 and current_value > lo:
                # Falling trend — when will it hit the lower threshold?
                minutes_to_lower = (current_value - lo) / abs(rate_per_minute)
                if minutes_to_lower <= 60:
                    lines.append(
                        f"\n⚠️  PREDICTION: At current rate, {sensor_name} will reach "
                        f"the lower threshold of {lo} {unit} in "
                        f"{minutes_to_lower:.1f} minutes."
                    )
                else:
                    lines.append(
                        f"\n✅ PREDICTION: {sensor_name} falling but will take "
                        f"{minutes_to_lower:.1f} minutes to reach lower threshold — "
                        f"monitor but no immediate action needed."
                    )

            elif abs(rate_per_minute) < 0.01:
                lines.append(
                    f"\n✅ PREDICTION: {sensor_name} is stable — "
                    f"rate of change is near zero ({rate_per_minute:+.4f} {unit}/min)."
                )

        return "\n".join(lines)

    except Exception as e:
        return f"ERROR in trend analysis for '{sensor_name}': {e}"
```

---

---

# PART 3 — TOOL SCHEMAS (What Gemini Sees)

This is the most important file for agent behaviour.
The LLM reads these descriptions to decide which tool to call.
**Write them as if explaining to a smart colleague, not a machine.**

Create `agent/tool_schemas.py`:

```python
"""
tool_schemas.py
Defines the function schemas sent to Gemini so it knows
what tools exist, what they do, and what arguments they take.

Senior rule: Clear descriptions = correct tool selection.
Vague descriptions = agent calls wrong tools or skips tools it needs.
"""

from vertexai.generative_models import FunctionDeclaration, Tool

# ── Tool 1 ─────────────────────────────────────────────────────────────
fetch_realtime_sensors_schema = FunctionDeclaration(
    name="fetch_realtime_sensors",
    description=(
        "Fetches the current real-time values of ALL boiler, turbine and chimney "
        "sensors from the last 5 minutes. "
        "Boiler (BOILER_001): main_steam_flow, main_steam_temp_boiler, "
        "main_steam_pressure_boiler, reheat_steam_temp_boiler, "
        "superheater_desup_flow, reheater_desup_flow, feedwater_temp, "
        "feedwater_flow, feedwater_pressure, flue_gas_temp, oxygen_level. "
        "Turbine: main_steam_temp_turbine, main_steam_pressure_turbine, "
        "reheat_steam_temp_turbine, reheat_steam_pressure_turbine, "
        "control_stage_pressure, high_exhaust_pressure, condenser_vacuum, "
        "circ_water_outlet_temp. "
        "Chimney (CHIMNEY_001): flue_temp, co2, o2, co, draft, stack_velocity. "
        "Each reading includes a NORMAL / WARNING / CRITICAL status. "
        "ALWAYS call this tool first when the user asks about current conditions, "
        "safety, or any question that requires knowing present sensor values."
    ),
    parameters={
        "type": "object",
        "properties": {},   # no parameters — always fetches all sensors
        "required": [],
    },
)

# ── Tool 2 ─────────────────────────────────────────────────────────────
search_knowledge_base_schema = FunctionDeclaration(
    name="search_knowledge_base",
    description=(
        "Searches the boiler and chimney technical knowledge base for "
        "fault guides, sensor interpretation documents, safety procedures, "
        "and diagnostic information. "
        "Use this tool when you need to explain WHY a fault happens, "
        "HOW to fix it, WHAT a sensor reading means, or what action to take. "
        "This tool contains detailed guides for the fault codes raised by the "
        "simulators: HIGH_MAIN_STEAM_PRESSURE, LOW_FEEDWATER_FLOW, "
        "LOW_FEEDWATER_PRESSURE, HIGH_FLUE_GAS_TEMP, LOW_OXYGEN, HIGH_OXYGEN, "
        "HIGH_REHEAT_TEMP, CONDENSER_VACUUM_LOSS, HIGH_CIRC_WATER_TEMP, "
        "EXCESSIVE_DESUP_SPRAY (boiler/turbine) and BLOCKED_FLUE, HIGH_CO, "
        "LOW_DRAFT, HIGH_FLUE_TEMP (chimney). "
        "Also contains combustion theory, draft pressure interpretation, "
        "and water level management guides."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural language search query describing what information you need. "
                    "Be specific. Examples: "
                    "'HIGH_PRESSURE fault causes and immediate actions', "
                    "'how to interpret CO2 percentage in flue gas', "
                    "'water level dropping below 40 percent diagnosis', "
                    "'blocked flue symptoms and repair steps'"
                ),
            }
        },
        "required": ["query"],
    },
)

# ── Tool 3 ─────────────────────────────────────────────────────────────
get_fault_history_schema = FunctionDeclaration(
    name="get_fault_history",
    description=(
        "Retrieves the history of fault events from the boiler and chimney "
        "monitoring system for the last N minutes. "
        "Returns fault code, severity (CRITICAL/WARNING), affected sensor, "
        "timestamp, and fault message for each event. "
        "Use this tool when: the user asks about recent faults, you want to "
        "check if a current out-of-range reading is part of an ongoing fault, "
        "or you need to provide historical context in your answer."
    ),
    parameters={
        "type": "object",
        "properties": {
            "minutes": {
                "type": "integer",
                "description": (
                    "Number of minutes of fault history to retrieve. "
                    "Use 30 for very recent faults, "
                    "60 for the last hour (default), "
                    "1440 for the last 24 hours."
                ),
            }
        },
        "required": [],
    },
)

# ── Tool 4 ─────────────────────────────────────────────────────────────
predict_trend_schema = FunctionDeclaration(
    name="predict_trend",
    description=(
        "Analyses the historical trend of a specific sensor over the last "
        "N minutes and predicts whether it will reach a dangerous threshold, "
        "and how many minutes until it does. "
        "Use this tool when: the user asks if something will get worse, "
        "wants to know how long before a fault occurs, or when you notice "
        "a sensor is moving toward its threshold and want to give a "
        "proactive warning. "
        "This tool performs linear trend analysis and time-to-threshold prediction."
    ),
    parameters={
        "type": "object",
        "properties": {
            "sensor_name": {
                "type": "string",
                "description": (
                    "Name of the sensor to analyse. "
                    "Boiler: 'main_steam_flow', 'main_steam_temp_boiler', "
                    "'main_steam_pressure_boiler', 'reheat_steam_temp_boiler', "
                    "'superheater_desup_flow', 'reheater_desup_flow', "
                    "'feedwater_temp', 'feedwater_flow', 'feedwater_pressure', "
                    "'flue_gas_temp', 'oxygen_level'. "
                    "Turbine: 'main_steam_temp_turbine', "
                    "'main_steam_pressure_turbine', 'reheat_steam_temp_turbine', "
                    "'reheat_steam_pressure_turbine', 'control_stage_pressure', "
                    "'high_exhaust_pressure', 'condenser_vacuum', "
                    "'circ_water_outlet_temp'. "
                    "Chimney: 'flue_temp', 'co2', 'o2', 'co', 'draft', "
                    "'stack_velocity'."
                ),
            },
            "window_minutes": {
                "type": "integer",
                "description": (
                    "How many minutes of history to use for trend analysis. "
                    "30 minutes is good for detecting recent changes. "
                    "60 minutes is better for slower-changing trends."
                ),
            },
        },
        "required": ["sensor_name"],
    },
)

# ── Bundle all tools ────────────────────────────────────────────────────
BOILER_AGENT_TOOLS = Tool(
    function_declarations=[
        fetch_realtime_sensors_schema,
        search_knowledge_base_schema,
        get_fault_history_schema,
        predict_trend_schema,
    ]
)
```

---

---

# PART 4 — THE AGENT ORCHESTRATOR (The Brain)

This is the core of the entire system.
The orchestrator runs the ReAct loop — it sends questions to Gemini,
executes the tools it asks for, and keeps going until Gemini gives a final answer.

Create `agent/orchestrator.py`:

```python
"""
orchestrator.py — The Agentic RAG Brain

This file implements the ReAct loop:
  1. Send question + tool schemas to fine-tuned Gemini
  2. Gemini returns either: a tool_call OR a final text answer
  3. If tool_call → execute the Python function → send result back to Gemini
  4. If final answer → return it with all metadata

The fine-tuned model reasons about WHICH tools to call based on the question.
The orchestrator EXECUTES those calls and feeds results back.
"""

import vertexai
from vertexai.generative_models import (
    GenerativeModel,
    GenerationConfig,
    Content,
    Part,
)
import json
import time
from datetime import datetime

import sys
sys.path.append("..")
from config import (
    GCP_PROJECT_ID, GCP_REGION, FINE_TUNED_MODEL_ENDPOINT,
    GEMINI_TEMPERATURE, GEMINI_MAX_TOKENS, GEMINI_TOP_P,
    MAX_AGENT_STEPS,
)
from agent.tool_schemas import BOILER_AGENT_TOOLS
from agent.tools.realtime_tool   import fetch_realtime_sensors
from agent.tools.knowledge_tool  import search_knowledge_base
from agent.tools.fault_tool      import get_fault_history
from agent.tools.prediction_tool import predict_trend

# ── Initialise Vertex AI ────────────────────────────────────────────────
vertexai.init(project=GCP_PROJECT_ID, location=GCP_REGION)


# ── Tool dispatcher ─────────────────────────────────────────────────────
# Maps tool name (string from Gemini) → actual Python function
TOOL_REGISTRY = {
    "fetch_realtime_sensors": fetch_realtime_sensors,
    "search_knowledge_base":  search_knowledge_base,
    "get_fault_history":      get_fault_history,
    "predict_trend":          predict_trend,
}


def execute_tool(tool_name: str, tool_args: dict) -> str:
    """
    Executes a tool by name with given arguments.
    Returns the result as a string, always — never raises exceptions.
    """
    func = TOOL_REGISTRY.get(tool_name)
    if func is None:
        return f"ERROR: Unknown tool '{tool_name}'. Available tools: {list(TOOL_REGISTRY.keys())}"

    try:
        result = func(**tool_args)
        return str(result)
    except TypeError as e:
        # Wrong arguments passed
        return f"ERROR: Wrong arguments for tool '{tool_name}': {e}"
    except Exception as e:
        return f"ERROR: Tool '{tool_name}' failed: {e}"


class BoilerAgentOrchestrator:

    def __init__(self):
        # System instruction — injected once, shapes all responses
        self.system_instruction = """You are BOILER-AI, a senior industrial engineer specialising in boiler and chimney systems.

Your expertise:
- You diagnose faults based on real-time sensor data
- You predict what will go wrong before it happens
- You give specific, step-by-step fix instructions
- You explain WHY faults happen, not just WHAT they are
- You use Indian Boiler Regulations (IBR) standards

Your behaviour rules:
1. ALWAYS call fetch_realtime_sensors first for any question about current conditions
2. ALWAYS call search_knowledge_base when explaining fault causes or fix procedures
3. Call get_fault_history when the user asks about recent events or patterns
4. Call predict_trend when a sensor is moving toward a threshold or user asks about future risk
5. After collecting data from tools, synthesise a complete, actionable answer
6. Structure answers as: Current Status → Diagnosis → Root Cause → Immediate Actions → Prevention
7. Be specific with numbers: say "pressure is 18.2 bar, 29% above the 14 bar limit" not "pressure is high"
8. Mark CRITICAL faults clearly with 🚨, WARNING with ⚠️, normal with ✅"""

        # Load fine-tuned model
        self.model = GenerativeModel(
            model_name=FINE_TUNED_MODEL_ENDPOINT,
            system_instruction=self.system_instruction,
        )

        self.gen_config = GenerationConfig(
            temperature=GEMINI_TEMPERATURE,
            max_output_tokens=GEMINI_MAX_TOKENS,
            top_p=GEMINI_TOP_P,
        )

        print(f"✅ BoilerAgentOrchestrator ready — model: {FINE_TUNED_MODEL_ENDPOINT}")

    def run(self, user_question: str) -> dict:
        """
        Main entry point. Runs the full ReAct loop for one user question.

        Returns:
            {
                "answer":       str — final answer text
                "steps":        list — each tool call made with args and result
                "total_steps":  int — how many tool calls were made
                "latency_ms":   float — total time in milliseconds
                "question":     str — original question
                "timestamp":    str — ISO timestamp
            }
        """
        start_time = time.time()
        steps      = []
        step_count = 0

        # ── Build conversation history ─────────────────────────────
        # Gemini function calling requires maintaining a full conversation
        # as a list of Content objects (user + model + tool turns)
        messages = [
            Content(role="user", parts=[Part.from_text(user_question)])
        ]

        print(f"\n{'='*60}")
        print(f"🧠 AGENT: Processing question: '{user_question}'")
        print(f"{'='*60}")

        final_answer = None

        # ── ReAct Loop ─────────────────────────────────────────────
        while step_count < MAX_AGENT_STEPS:
            step_count += 1
            print(f"\n🔄 Step {step_count}/{MAX_AGENT_STEPS}")

            # Send current conversation to fine-tuned Gemini
            response = self.model.generate_content(
                messages,
                tools=[BOILER_AGENT_TOOLS],
                generation_config=self.gen_config,
            )

            candidate = response.candidates[0]
            content   = candidate.content

            # ── Check what Gemini returned ─────────────────────────
            # Case A: Gemini wants to call a tool
            tool_calls = [
                part for part in content.parts
                if hasattr(part, "function_call") and part.function_call.name
            ]

            # Case B: Gemini returned a text answer
            text_parts = [
                part for part in content.parts
                if hasattr(part, "text") and part.text.strip()
            ]

            if tool_calls:
                # ── Execute all requested tool calls ─────────────
                tool_results_parts = []

                for part in tool_calls:
                    fc        = part.function_call
                    tool_name = fc.name
                    tool_args = dict(fc.args)

                    print(f"  🔧 Tool call: {tool_name}({tool_args})")

                    # Execute the tool
                    tool_result = execute_tool(tool_name, tool_args)

                    # Log the step
                    steps.append({
                        "step":        step_count,
                        "tool":        tool_name,
                        "args":        tool_args,
                        "result_preview": tool_result[:200] + "..." if len(tool_result) > 200 else tool_result,
                    })

                    print(f"  📊 Result preview: {tool_result[:150]}...")

                    # Build tool result part for Gemini
                    tool_results_parts.append(
                        Part.from_function_response(
                            name=tool_name,
                            response={"result": tool_result},
                        )
                    )

                # Add Gemini's tool call request to history
                messages.append(Content(role="model", parts=content.parts))

                # Add tool results to history
                messages.append(Content(role="user", parts=tool_results_parts))

            elif text_parts:
                # ── Gemini gave a final text answer ──────────────
                final_answer = "\n".join(p.text for p in text_parts).strip()
                print(f"\n✅ Final answer received ({len(final_answer)} chars)")
                break

            else:
                # Unexpected — no tool call and no text
                print(f"  ⚠️  Step {step_count}: Empty response from Gemini")
                break

        # ── Handle max steps reached ────────────────────────────────
        if final_answer is None:
            final_answer = (
                "I gathered the following data but reached the maximum reasoning steps. "
                "Here is a summary based on what I collected:\n\n"
                + "\n".join([f"Step {s['step']}: {s['tool']} → {s['result_preview']}"
                              for s in steps])
            )

        latency_ms = round((time.time() - start_time) * 1000, 1)

        print(f"⏱️  Total latency: {latency_ms}ms | Steps taken: {len(steps)}")

        return {
            "answer":      final_answer,
            "steps":       steps,
            "total_steps": len(steps),
            "latency_ms":  latency_ms,
            "question":    user_question,
            "timestamp":   datetime.utcnow().isoformat() + "Z",
        }
```

---

---

# PART 5 — EVALUATION METRICS

Create `evaluation/evaluator.py`:

```python
"""
Evaluation Engine for Agentic RAG
Measures quality of every chatbot answer using RAGAS metrics.
Logs scores to InfluxDB → visible on Grafana dashboard.

Metrics:
  faithfulness      — did answer use only provided context? (no hallucination)
  answer_relevancy  — does answer address the question asked?
  tool_precision    — did agent call the right tools?
  latency_ms        — how fast was the response?
  steps_taken       — how many tool calls were needed?
"""

from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy
from datasets import Dataset
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from langchain_google_vertexai import ChatVertexAI
from langchain_community.embeddings import HuggingFaceEmbeddings
from datetime import datetime
import numpy as np
import sys
sys.path.append("..")
from config import (
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    GCP_PROJECT_ID, GCP_REGION, EMBEDDING_MODEL
)

_influx    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
_write_api = _influx.write_api(write_options=SYNCHRONOUS)


class BoilerEvaluator:

    def __init__(self):
        # Use base Gemini (not fine-tuned) as the judge model
        # The judge evaluates quality — it should be a general model
        self.judge_llm = ChatVertexAI(
            model_name="gemini-1.5-flash",
            project=GCP_PROJECT_ID,
            location=GCP_REGION,
            temperature=0,
        )
        self.embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        print("✅ Evaluator ready")

    def evaluate(
        self,
        question:    str,
        answer:      str,
        contexts:    list,      # list of strings — tool results used as context
        latency_ms:  float,
        steps_taken: int,
        tools_used:  list,
    ) -> dict:
        """
        Run evaluation metrics on one Q&A interaction.
        Logs scores to InfluxDB automatically.
        """

        # ── RAGAS evaluation ───────────────────────────────────────
        eval_dataset = Dataset.from_dict({
            "question": [question],
            "answer":   [answer],
            "contexts": [contexts],
        })

        try:
            result = evaluate(
                dataset=eval_dataset,
                metrics=[faithfulness, answer_relevancy],
                llm=self.judge_llm,
                embeddings=self.embeddings,
                raise_exceptions=False,
            )
            df     = result.to_pandas()
            faith  = round(float(df["faithfulness"].iloc[0] or 0), 3)
            relev  = round(float(df["answer_relevancy"].iloc[0] or 0), 3)
        except Exception as e:
            print(f"⚠️  RAGAS error: {e}")
            faith = 0.0
            relev = 0.0

        # ── Tool selection quality score ───────────────────────────
        # Check if agent called expected tools for this type of question
        expected_tools = self._expected_tools(question)
        if expected_tools:
            precision = len(set(tools_used) & set(expected_tools)) / len(expected_tools)
        else:
            precision = 1.0
        precision = round(precision, 3)

        # ── Overall quality score ──────────────────────────────────
        overall = round(float(np.mean([faith, relev, precision])), 3)

        scores = {
            "faithfulness":     faith,
            "answer_relevancy": relev,
            "tool_precision":   precision,
            "overall_quality":  overall,
            "latency_ms":       latency_ms,
            "steps_taken":      steps_taken,
            "tools_used":       ",".join(tools_used),
            "timestamp":        datetime.utcnow().isoformat() + "Z",
        }

        # ── Log to InfluxDB ────────────────────────────────────────
        self._log_influx(question, scores)

        print(
            f"📊 Eval | faith={faith:.2f} relev={relev:.2f} "
            f"tool_prec={precision:.2f} overall={overall:.2f} "
            f"latency={latency_ms}ms steps={steps_taken}"
        )

        return scores

    def _expected_tools(self, question: str) -> list:
        """Heuristic: what tools SHOULD have been called for this question."""
        q = question.lower()
        expected = []
        if any(w in q for w in ["current", "now", "reading", "safe", "status", "value"]):
            expected.append("fetch_realtime_sensors")
        if any(w in q for w in ["fault", "why", "cause", "fix", "how to", "what is"]):
            expected.append("search_knowledge_base")
        if any(w in q for w in ["recent", "history", "occurred", "happened", "last"]):
            expected.append("get_fault_history")
        if any(w in q for w in ["trend", "predict", "will", "going to", "long before"]):
            expected.append("predict_trend")
        return expected

    def _log_influx(self, question: str, scores: dict):
        point = (
            Point("chatbot_evaluation")
            .tag("question_preview", question[:60])
            .field("faithfulness",     scores["faithfulness"])
            .field("answer_relevancy", scores["answer_relevancy"])
            .field("tool_precision",   scores["tool_precision"])
            .field("overall_quality",  scores["overall_quality"])
            .field("latency_ms",       scores["latency_ms"])
            .field("steps_taken",      float(scores["steps_taken"]))
            .field("tools_used",       scores["tools_used"])
            .time(scores["timestamp"])
        )
        try:
            _write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
        except Exception as e:
            print(f"⚠️  Failed to log eval to InfluxDB: {e}")
```

---

---

# PART 6 — FASTAPI (Production API)

Create `api/chatbot_api.py`:

```python
"""
FastAPI — Boiler Agentic RAG API
Endpoints:
  POST /chat          — run agent, returns answer + steps + eval scores
  GET  /status        — live sensor snapshot
  GET  /metrics       — 24h evaluation averages from InfluxDB
  GET  /health        — service health check
  WS   /ws/chat       — WebSocket for live streaming
"""

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import json, sys
sys.path.append("..")

from agent.orchestrator   import BoilerAgentOrchestrator
from evaluation.evaluator import BoilerEvaluator
from agent.tools.realtime_tool import fetch_realtime_sensors
from agent.tools.fault_tool    import get_fault_history
from influxdb_client import InfluxDBClient
from config import INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET

app = FastAPI(
    title="Boiler Agentic RAG Chatbot",
    description="Fine-tuned Gemini 2.5 Flash + Agentic RAG for boiler/chimney monitoring",
    version="3.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialise once at startup (heavy objects)
agent     = BoilerAgentOrchestrator()
evaluator = BoilerEvaluator()
influx    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)


class ChatRequest(BaseModel):
    question:    str
    session_id:  str = "default"
    evaluate:    bool = True   # set False to skip eval (faster, for testing)


@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.post("/chat")
def chat(request: ChatRequest):
    """
    Main chat endpoint.
    Runs the Agentic RAG loop and returns:
    - answer: final grounded response
    - steps: which tools were called and with what results
    - eval_scores: faithfulness, relevancy, tool precision, latency
    """
    # Run agent
    result = agent.run(request.question)

    # Collect contexts for evaluation (all tool results)
    contexts   = [s["result_preview"] for s in result["steps"]]
    tools_used = [s["tool"] for s in result["steps"]]

    # Evaluate (unless disabled)
    eval_scores = {}
    if request.evaluate and contexts:
        eval_scores = evaluator.evaluate(
            question=request.question,
            answer=result["answer"],
            contexts=contexts,
            latency_ms=result["latency_ms"],
            steps_taken=result["total_steps"],
            tools_used=tools_used,
        )

    return {
        "question":    request.question,
        "answer":      result["answer"],
        "steps":       result["steps"],
        "total_steps": result["total_steps"],
        "latency_ms":  result["latency_ms"],
        "eval_scores": eval_scores,
        "timestamp":   result["timestamp"],
    }


@app.get("/status")
def status():
    """Returns live sensor readings and recent faults."""
    return {
        "sensors":   fetch_realtime_sensors(),
        "faults":    get_fault_history(minutes=60),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/metrics")
def metrics():
    """Returns average evaluation scores from last 24 hours."""
    query = f"""
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -24h)
      |> filter(fn: (r) => r["_measurement"] == "chatbot_evaluation")
      |> filter(fn: (r) =>
           r["_field"] == "faithfulness" or
           r["_field"] == "answer_relevancy" or
           r["_field"] == "tool_precision" or
           r["_field"] == "overall_quality" or
           r["_field"] == "latency_ms" or
           r["_field"] == "steps_taken")
      |> mean()
    """
    try:
        avgs = {}
        for table in influx.query_api().query(query):
            for record in table.records:
                avgs[record.get_field()] = round(record.get_value(), 3)
        return {"averages_24h": avgs, "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        return {"error": str(e)}


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data     = await websocket.receive_text()
            payload  = json.loads(data)
            question = payload.get("question", "")
            result   = agent.run(question)
            await websocket.send_json({
                "answer":      result["answer"],
                "steps":       result["steps"],
                "latency_ms":  result["latency_ms"],
                "timestamp":   result["timestamp"],
            })
    except Exception:
        pass
```

Start the API:
```bash
uvicorn api.chatbot_api:app --host 0.0.0.0 --port 8000 --reload
```

---

---

# PART 7 — GRAFANA EVALUATION DASHBOARD

Since you already have Grafana running, create a new dashboard called
**"Chatbot AI Metrics"** with these panels:

## Panel 1 — Overall Quality Score (Gauge)
```flux
from(bucket: "boiler_data")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "chatbot_evaluation")
  |> filter(fn: (r) => r["_field"] == "overall_quality")
  |> mean()
```
Type: **Gauge** | Min: 0 | Max: 1
Thresholds: 0.0-0.5 🔴 | 0.5-0.75 🟡 | 0.75-1.0 🟢

## Panel 2 — All Scores Over Time (Time Series)
```flux
from(bucket: "boiler_data")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "chatbot_evaluation")
  |> filter(fn: (r) =>
       r["_field"] == "faithfulness" or
       r["_field"] == "answer_relevancy" or
       r["_field"] == "tool_precision")
```
Type: **Time series** (3 lines: faithfulness, relevancy, tool precision)

## Panel 3 — Response Latency
```flux
from(bucket: "boiler_data")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "chatbot_evaluation")
  |> filter(fn: (r) => r["_field"] == "latency_ms")
```
Type: **Time series** | Unit: **ms** | Alert: > 8000ms

## Panel 4 — Average Steps Per Query (Stat)
```flux
from(bucket: "boiler_data")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "chatbot_evaluation")
  |> filter(fn: (r) => r["_field"] == "steps_taken")
  |> mean()
```
Type: **Stat** — tells you average tool calls per question

---

---

# PART 8 — STARTUP & TEST

## Step 8.1 — Install all dependencies

```bash
pip install \
  google-cloud-aiplatform \
  vertexai \
  langchain-google-vertexai \
  chromadb \
  sentence-transformers \
  influxdb-client \
  ragas \
  langchain-community \
  fastapi \
  uvicorn \
  paho-mqtt \
  numpy
```

## Step 8.2 — Set environment variables

Add these to your existing `.env` (already loaded by `assistant/config.py`):

```bash
GCP_PROJECT_ID=your-gcp-project-id
GCP_REGION=us-central1
TUNED_MODEL_ENDPOINT_v4=projects/your-project/locations/us-central1/endpoints/your-id
INFLUX_URL=http://localhost:8086
INFLUX_TOKEN=my-super-secret-token-123
INFLUX_ORG=boiler_org
INFLUX_BUCKET=boiler_data
CHROMA_PATH=./chroma_db
```

Then authenticate the local shell with Google Cloud:

```bash
gcloud auth application-default login
```

## Step 8.3 — Index knowledge base (once)

```bash
cd knowledge_base
python indexer.py
# Output: ✅ Indexed 12 knowledge documents
```

## Step 8.4 — Start the full system

```bash
# Terminal 1: Docker services
docker-compose up -d

# Terminal 2: Simulators (already running from before)
python simulators/boiler_simulator.py &
python simulators/chimney_simulator.py &

# Terminal 3: Consumers (already running from before)
python consumers/influx_consumer.py &
python consumers/fault_detector.py &

# Terminal 4: Chatbot API
uvicorn api.chatbot_api:app --host 0.0.0.0 --port 8000 --reload
```

## Step 8.5 — Test the agent

```bash
# Test 1: Current status question
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Is the boiler safe to operate right now?"}'

# Test 2: Fault diagnosis question
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Pressure seems high. Why is this happening and what do I do?"}'

# Test 3: Prediction question
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Pressure has been rising for 20 minutes. Will it reach a critical level?"}'

# Test 4: Historical fault question
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What faults have happened in the last hour?"}'

# Get metrics
curl http://localhost:8000/metrics
```

Expected response for Test 1:
```json
{
  "question": "Is the boiler safe to operate right now?",
  "answer": "✅ BOILER STATUS: SAFE\n\nCurrent readings...",
  "steps": [
    {"step": 1, "tool": "fetch_realtime_sensors", "args": {}, "result_preview": "..."},
    {"step": 2, "tool": "get_fault_history", "args": {"minutes": 60}, "result_preview": "..."}
  ],
  "total_steps": 2,
  "latency_ms": 3241.5,
  "eval_scores": {
    "faithfulness": 0.91,
    "answer_relevancy": 0.88,
    "tool_precision": 1.0,
    "overall_quality": 0.93
  }
}
```

---

---

# PART 9 — WHAT GOOD LOOKS LIKE

## Agent reasoning for different question types

| Question type | Tools agent calls | Why |
|---|---|---|
| "Is boiler safe now?" | fetch_realtime + get_fault_history | Needs current data + fault context |
| "Why is pressure high?" | fetch_realtime + search_knowledge + get_fault_history | Needs data + cause guide + fault history |
| "Will pressure get worse?" | fetch_realtime + predict_trend | Needs current state + trend calculation |
| "What is HIGH_PRESSURE fault?" | search_knowledge | Pure knowledge question, no live data needed |
| "What happened last hour?" | get_fault_history | Pure history question |

## Target evaluation scores

| Metric | Minimum | Good | Target |
|---|---|---|---|
| Faithfulness | 0.70 | 0.80 | **> 0.85** |
| Answer Relevancy | 0.75 | 0.85 | **> 0.88** |
| Tool Precision | 0.80 | 0.90 | **> 0.90** |
| Overall Quality | 0.75 | 0.85 | **> 0.87** |
| Latency | < 10s | < 6s | **< 4s** |
| Steps per query | — | 2–3 | **2–4** |

## What low scores mean and how to fix them

**Low Faithfulness (< 0.7):** Agent is hallucinating — answering from training
memory instead of tool results. Fix: make system instruction stricter:
*"Only use information returned by tools. Never use general knowledge."*

**Low Answer Relevancy (< 0.75):** Agent is answering a different question.
Fix: check if the right tools were called. Improve tool descriptions in `tool_schemas.py`.

**Low Tool Precision (< 0.80):** Agent calls wrong tools or misses obvious ones.
Fix: improve tool descriptions — make them more specific about when to use each.

**High Latency (> 8s):** Too many tool calls or slow Vertex AI response.
Fix: reduce `MAX_AGENT_STEPS` from 6 to 4. Cache knowledge base results.

---

# PART 10 — REQUIREMENTS

```
# Vertex AI + Gemini
google-cloud-aiplatform>=1.38.0
vertexai>=1.38.0
langchain-google-vertexai>=0.0.6

# Vector DB
chromadb==0.4.22
sentence-transformers==2.3.1

# Time-series DB
influxdb-client==1.36.1

# Evaluation
ragas==0.1.7
langchain-community==0.0.24
datasets==2.17.0

# API
fastapi==0.109.2
uvicorn==0.27.1
websockets==12.0
pydantic==2.5.3

# IoT
paho-mqtt==1.6.1
numpy==1.26.4
```

---

*Stack: Vertex AI · Fine-tuned Gemini 2.5 Flash · Agentic RAG · Native Function Calling · ChromaDB · InfluxDB · RAGAS · FastAPI · Docker*
