# 🏭 Boiler & Chimney AI Chatbot — Complete System Documentation
### Fine-Tuning + RAG + Real-Time Dashboard + Evaluation Metrics
#### Production-Grade | Fresher-Friendly | Full Code

---

> **Where you are now:** Grafana dashboard ✅ done. Simulators ✅ running. InfluxDB ✅ storing data.
> **What this document covers:** Building the AI chatbot layer on top of what you already have — combining fine-tuning + RAG for maximum accuracy, plus evaluation metrics so you can measure and prove how good the chatbot is.

---

## 📐 Complete System Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     COMPLETE BOILER AI SYSTEM                            │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  ALREADY BUILT ✅                                                │    │
│  │  Boiler/Chimney Simulators → MQTT → InfluxDB → Grafana          │    │
│  │  Fault Detector → fault_events in InfluxDB                      │    │
│  └──────────────────────────────┬──────────────────────────────────┘    │
│                                 │ real-time data flows here             │
│  ┌──────────────────────────────▼──────────────────────────────────┐    │
│  │  LAYER A — KNOWLEDGE BASE (build once)                          │    │
│  │  Boiler/chimney fault guides + sensor interpretation docs       │    │
│  │  → indexed into ChromaDB (vector search)                        │    │
│  └──────────────────────────────┬──────────────────────────────────┘    │
│                                 │                                       │
│  ┌──────────────────────────────▼──────────────────────────────────┐    │
│  │  LAYER B — FINE-TUNING (run once, on Day 5)                     │    │
│  │  JSONL dataset from InfluxDB history + fault explanations       │    │
│  │  → Mistral 7B + LoRA → domain-aware model saved locally         │    │
│  └──────────────────────────────┬──────────────────────────────────┘    │
│                                 │                                       │
│  ┌──────────────────────────────▼──────────────────────────────────┐    │
│  │  LAYER C — RAG PIPELINE (runs on every query)                   │    │
│  │  InfluxDB → real-time readings → context                        │    │
│  │  ChromaDB → relevant fault/sensor guides → knowledge            │    │
│  │  Both injected into prompt → fine-tuned LLM → answer            │    │
│  └──────────────────────────────┬──────────────────────────────────┘    │
│                                 │                                       │
│  ┌──────────────────────────────▼──────────────────────────────────┐    │
│  │  LAYER D — EVALUATION METRICS (runs after every answer)         │    │
│  │  Faithfulness · Context Recall · Answer Relevancy · Latency     │    │
│  │  Scores logged to InfluxDB → visible in Grafana                 │    │
│  └──────────────────────────────┬──────────────────────────────────┘    │
│                                 │                                       │
│  ┌──────────────────────────────▼──────────────────────────────────┐    │
│  │  LAYER E — FastAPI + React Dashboard                            │    │
│  │  /chat endpoint · /status endpoint · /metrics endpoint          │    │
│  │  React UI: live sensor panel + chat window side by side         │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 📚 New Concepts — Read Before Building

| Concept | What it means in your system |
|---|---|
| **Fine-Tuning purpose** | Teaches Mistral *how to reason* about boiler data — fault causes, safety rules, domain vocabulary |
| **RAG purpose** | Injects *current* sensor values and fault history into every prompt at query time |
| **Why both together** | Fine-tuning = the engineer's brain. RAG = the engineer's eyes on live instruments |
| **Faithfulness** | Did the answer only use information from the provided context? (no hallucination) |
| **Context Recall** | Did the retrieved documents actually contain what was needed to answer? |
| **Answer Relevancy** | Does the answer actually address the question asked? |
| **RAGAS** | A Python library that measures all three metrics automatically |
| **LoRA adapter** | The small trained weight file saved after fine-tuning. ~50MB, not the full 7B model |
| **Ollama** | Runs Mistral 7B locally on your machine. Free. No internet needed after download |

---

---

# PART 1 — WHY FINE-TUNING + RAG TOGETHER

## The problem with RAG alone

RAG alone gives the model real-time data but the model still reasons like a general assistant. It might say:

> "Pressure of 18 bar seems high. You should probably check the boiler."

That is vague. A domain-expert answer looks like:

> "Pressure at 18 bar is 28% above the critical threshold of 14 bar. This indicates a HIGH_PRESSURE fault. Likely cause: pressure relief valve stuck closed or downstream steam outlet blocked. Immediate action: reduce burner firing rate, manually check relief valve, inspect steam outlet. Do not continue operation."

The difference is **domain reasoning** — knowing exactly what 18 bar means for this type of boiler, knowing the causes, knowing the exact action steps. Fine-tuning bakes this in.

## The problem with fine-tuning alone

Fine-tuning gives domain reasoning but the model has no idea what the sensor values are *right now*. It cannot say "pressure is currently 18 bar" because that value wasn't in its training data. Every answer would be generic: "check your pressure" instead of "pressure is 18 bar, which is a CRITICAL fault."

## Together: best of both

```
Fine-tuned model knows:             RAG provides:
─────────────────────────           ────────────────────────────
What HIGH_PRESSURE means            pressure = 18.2 bar RIGHT NOW
What causes it                      last fault: 4 minutes ago
Exact fix steps                     water_level = 52% (normal)
When it is dangerous                co = 23 ppm (normal)
How sensors relate to each other    flue_temp = 210°C (normal)

Combined answer: specific, accurate, actionable, grounded in live data
```

---

---

# PART 2 — KNOWLEDGE BASE (build once)

This is the document library that goes into ChromaDB. The fine-tuned model uses domain reasoning; the knowledge base provides the detailed reference material retrieved at query time.

## Step 2.1 — Create knowledge base documents

Create `knowledge_base/boiler_guides.py`:

```python
"""
Boiler & Chimney Knowledge Base
Complete fault guides, sensor interpretation, and diagnostic documents.
These are indexed into ChromaDB for RAG retrieval.
"""

KNOWLEDGE_DOCUMENTS = [

    # ── BOILER FAULT GUIDES ───────────────────────────────────────

    {
        "id": "fault_high_pressure",
        "title": "HIGH_PRESSURE Fault — Causes, Control, Prevention",
        "content": """
HIGH_PRESSURE fault triggers when boiler steam pressure exceeds 14 bar.
CRITICAL severity — immediate action required.

ROOT CAUSES (ranked by frequency):
1. Faulty pressure relief valve — valve not opening at set pressure
2. Downstream steam outlet closed or blocked — pressure has nowhere to go
3. Burner over-firing — heat input exceeds steam demand
4. Scale buildup on heating surfaces — reduces heat transfer, causes localised overheating
5. Feed water pump oversupply — too much water being converted to steam rapidly

STEP-BY-STEP CONTROL:
Step 1: Reduce burner to minimum firing rate immediately
Step 2: Verify steam outlet valve is open — check downstream isolation valves
Step 3: Manually test pressure relief valve — lift test lever briefly
Step 4: If pressure continues rising above 16 bar: SHUT DOWN BURNER COMPLETELY
Step 5: Do not restart until root cause identified and fixed

DIAGNOSIS CLUES:
- Sudden pressure spike → blocked outlet or stuck relief valve
- Gradual pressure rise over hours → scale buildup or demand mismatch
- Pressure high + flue temp high → scale on heat exchanger surfaces
- Pressure high + water level normal + fuel flow normal → relief valve fault

PREVENTION:
- Monthly pressure relief valve test
- Annual boiler inspection and descaling
- Install pressure trend alert at 12 bar (2 bar before critical)
- Log pressure history — gradual upward trend indicates scale formation

SAFETY: Do not operate above 15 bar. Above 18 bar, explosion risk increases significantly.
        """
    },

    {
        "id": "fault_low_water",
        "title": "LOW_WATER_LEVEL Fault — Causes, Control, Prevention",
        "content": """
LOW_WATER_LEVEL fault triggers when drum water level drops below 40%.
CRITICAL severity — most dangerous boiler condition.

ROOT CAUSES:
1. Feed water pump failure — electrical or mechanical fault
2. Feed water control valve closed or stuck shut
3. High steam demand exceeding feed water supply rate
4. Leaking boiler tube — water escaping into furnace
5. Water level sensor fault — giving false low reading

STEP-BY-STEP CONTROL:
Step 1: SHUT OFF BURNER IMMEDIATELY — no exceptions
Step 2: Do NOT add cold water to a hot boiler — thermal shock causes tube cracking
Step 3: Check feed water pump — is it running? Is suction valve open?
Step 4: Check feed water control valve — manual override to open if automatic failed
Step 5: Inspect visible boiler surfaces for steam/water leaks
Step 6: Let boiler cool to below 60°C before adding water if pump was off for >10 minutes
Step 7: Call qualified engineer before restarting

DIAGNOSIS CLUES:
- Level dropping fast + pressure dropping → tube leak (water escaping)
- Level dropping + pressure normal → pump/valve failure
- Level sensor fluctuating wildly → sensor fault, check physically
- Level low + feed water flow zero → pump or valve issue

WHY IT IS CRITICAL:
Running a boiler dry overheats the tubes. Heated dry tubes expand unevenly,
warp, crack, and can rupture. A tube rupture releases high-pressure steam
explosively. This is the cause of most boiler explosions.

NEVER fire a boiler with water level below 30%.
        """
    },

    {
        "id": "fault_high_temp",
        "title": "HIGH_TEMPERATURE Fault — Causes and Control",
        "content": """
HIGH_TEMPERATURE fault triggers when boiler water/steam temperature exceeds 100°C
above design specification (actual trigger: 100°C in this system).

ROOT CAUSES:
1. Scale or sludge deposits on heating surfaces — insulates water from absorbing heat
2. Burner over-firing — excess heat input
3. Low water circulation — water not moving through heat exchanger
4. Incorrect fuel-air ratio — rich mixture producing excess combustion heat
5. Blocked flue gases inside boiler — combustion products not exiting cleanly

CONTROL:
1. Reduce burner firing rate by 20% increments
2. Check water circulation — is circulation pump running?
3. Measure flue gas CO2 — if above 14%, mixture is too rich, add air
4. Check for scale: if flue temperature is also high, scale is likely

RELATIONSHIP WITH FLUE TEMPERATURE:
If boiler water temperature is high AND chimney flue temperature is also high,
scale buildup on heat exchanger is almost certainly the cause.
Heat cannot pass through scale to the water, so both the combustion side
(flue temp high) and water side (water temp high) run hot.
        """
    },

    {
        "id": "fault_high_co",
        "title": "HIGH_CO Fault — Causes, Control, Safety",
        "content": """
HIGH_CO fault triggers when carbon monoxide in chimney flue gas exceeds 50 ppm.
CRITICAL severity — personnel safety risk.

ROOT CAUSES:
1. Insufficient combustion air — not enough oxygen to complete combustion
2. Burner nozzle fouling — carbon deposits blocking fuel atomisation
3. Cracked heat exchanger — combustion gases bypassing and mixing with air
4. Blocked air intake filter — restricting primary combustion air
5. Incorrect fuel pressure — low pressure causes poor atomisation and incomplete burn

STEP-BY-STEP CONTROL:
Step 1: Open combustion air damper — increase air supply by 10% increments
Step 2: Measure O2 in flue gas — should rise as you add air (target 3-8% O2)
Step 3: If O2 rises but CO stays high — suspect burner nozzle fouling
Step 4: Check and replace air intake filter if blocked
Step 5: If CO exceeds 200 ppm — evacuate boiler room, shut down boiler

PERSONNEL SAFETY THRESHOLDS:
- 0-50 ppm: Normal operation range
- 50-200 ppm: WARNING — investigate immediately, ensure ventilation
- 200+ ppm: EVACUATE boiler room — risk of CO poisoning within hours
- 800+ ppm: Life-threatening within 2-3 hours of exposure

CO IS INVISIBLE AND ODOURLESS. Install a CO detector alarm in the boiler room.

DIAGNOSIS: HIGH_CO + LOW_O2 together = definitely insufficient air supply.
        """
    },

    {
        "id": "fault_blocked_flue",
        "title": "BLOCKED_FLUE Fault — Causes and Control",
        "content": """
BLOCKED_FLUE triggers when chimney draft pressure is less negative than -2 Pa.
Normal draft is -2 to -5 Pa (negative = suction pulling gases upward).

ROOT CAUSES:
1. Soot and ash accumulation inside chimney — narrows effective diameter
2. Bird nest or debris at chimney outlet
3. Collapsed chimney liner — internal structural failure
4. Downdraught — wind direction pushing air back down chimney
5. Negative building pressure — building HVAC creating backdraft

CONTROL:
1. Shut down boiler — do not operate with blocked flue
2. With boiler off, inspect chimney outlet visually from ground
3. Measure draft at multiple heights to locate blockage zone
4. Schedule chimney sweep — mechanical wire brush cleaning
5. If collapse suspected: camera inspection of liner

DRAFT PRESSURE INTERPRETATION:
- -2 to -5 Pa: Normal
- -1 to -2 Pa: Mild restriction — schedule inspection
- 0 Pa: No draft — blocked or severe downdraught
- Positive value: Back pressure — flue gases entering boiler room

CONSEQUENCE OF IGNORING:
Operating with blocked flue causes combustion gases including CO to
back-flow into the boiler room. CO accumulation is silent and fatal.
        """
    },

    {
        "id": "fault_high_flue_temp",
        "title": "HIGH_FLUE_TEMPERATURE Fault — Causes and Efficiency Impact",
        "content": """
HIGH_FLUE_TEMPERATURE triggers when chimney outlet temperature exceeds 250°C.
Normal range: 150-250°C.

ROOT CAUSES:
1. Scale buildup on boiler heat exchanger — heat not transferred to water
2. Excessive excess air — too much cold air diluting flue gases poorly
3. Damaged or missing flue baffles inside boiler — gases bypass heat exchanger
4. Boiler operating above design load
5. Short-cycling — boiler starts/stops frequently, never reaches steady state

EFFICIENCY IMPACT:
Every 10°C above optimal flue temperature = approximately 1% fuel waste.
At 280°C flue temperature vs optimal 200°C: 8% efficiency loss.
For a boiler consuming 10,000L of fuel per year, this is 800L wasted annually.

CONTROL:
1. Check O2 percentage — if above 8%, too much excess air, close damper slightly
2. Inspect flue baffles — replace missing or damaged baffles
3. Schedule heat exchanger descaling if scale suspected (see also HIGH_TEMP fault)
4. Review boiler sizing — is boiler oversized for current demand?

TREND ANALYSIS:
Flue temperature rising gradually over weeks with no setting changes = scale buildup.
Schedule descaling treatment.
        """
    },

    # ── MULTI-SENSOR DIAGNOSTIC GUIDES ───────────────────────────

    {
        "id": "diag_pressure_low_water",
        "title": "Combined Diagnosis: HIGH_PRESSURE + LOW_WATER_LEVEL",
        "content": """
When HIGH_PRESSURE and LOW_WATER_LEVEL occur simultaneously:
This is a DOUBLE CRITICAL situation. Shut down immediately, no exceptions.

WHAT IS HAPPENING:
Feed water system has likely failed. The boiler is running out of water
while heat continues — remaining water converts to steam faster than
supplied, simultaneously raising pressure and dropping level.

MOST LIKELY ROOT CAUSE: Feed water pump failure with burner still running.

IMMEDIATE RESPONSE (in exact order):
1. Shut off burner NOW
2. Do NOT open relief valve manually
3. Do NOT add cold water until boiler cools below 60°C
4. Isolate steam distribution outlets
5. Call qualified boiler engineer — do not restart without professional inspection

ROOT CAUSE INVESTIGATION:
- Check feed water pump power supply and mechanical state
- Review how long pump has been off (check MQTT message history)
- Inspect for tube leaks — could cause both symptoms simultaneously
        """
    },

    {
        "id": "diag_high_co2_low_o2",
        "title": "Combined Diagnosis: HIGH_CO2 + LOW_O2",
        "content": """
CO2 above 14% AND O2 below 3% simultaneously = rich combustion mixture.
Too much fuel relative to air. CO will also be elevated.

IMMEDIATE CAUSE: Insufficient combustion air reaching the burner.

CONTROLS (in order):
1. Increase air damper opening by 10% increments
2. Measure O2 after each adjustment — target 3-8% O2
3. Check air intake filter — replace if blocked
4. Inspect burner head air ports — clean carbon deposits with wire brush
5. Verify fuel pressure is within manufacturer specification — excess pressure = excess fuel

EXPECTED RESULT:
As you increase air: O2 rises, CO2 falls, CO falls.
Target steady state: O2 = 4-6%, CO2 = 10-12%, CO < 30 ppm.
        """
    },

    {
        "id": "diag_prediction_pressure_rising",
        "title": "Predictive Diagnosis: Pressure Rising Trend",
        "content": """
If boiler pressure is rising gradually over 15-30 minutes without a setpoint change:

LIKELY CAUSES IN ORDER:
1. Steam demand has dropped — less steam being consumed downstream
2. Burner firing rate has not adjusted to match lower demand
3. Scale buildup reducing heat transfer efficiency (slower — weeks/months pattern)
4. Pressure relief valve beginning to stick (fast rise pattern)

PREDICTION:
If pressure is currently at 12.5 bar and rising at 0.3 bar per 10 minutes,
it will reach the critical threshold of 14 bar in approximately 5 minutes.

PREVENTIVE ACTION:
1. Reduce burner firing rate by 15% now — before reaching critical
2. Check steam consumers downstream — has demand dropped?
3. Monitor pressure trend for next 10 minutes after adjustment

TREND INTERPRETATION:
- Rising faster than 0.5 bar/minute → blocked outlet or stuck relief valve → EMERGENCY
- Rising at 0.1-0.3 bar/minute → demand mismatch → adjust burner
- Gradual rise over days/weeks → scale buildup → schedule maintenance
        """
    },

    # ── SENSOR INTERPRETATION GUIDES ─────────────────────────────

    {
        "id": "guide_co2_interpretation",
        "title": "How to Interpret CO2 Percentage in Flue Gas",
        "content": """
CO2 percentage in chimney flue gas is the primary combustion efficiency indicator.

READING INTERPRETATION:
- Below 8% CO2: Excessive air — too much cold air diluting combustion gases
  → efficiency loss, high flue temperature
- 8-12% CO2: Good combustion, adequate excess air
- 12-14% CO2: Excellent efficiency, near-stoichiometric combustion (ideal)
- Above 14% CO2: Insufficient air — incomplete combustion, CO risk

INVERSE RELATIONSHIP WITH O2:
CO2 and O2 always move in opposite directions.
More air → O2 rises, CO2 falls.
Less air → O2 falls, CO2 rises.
Target: CO2 = 11-12% with O2 = 4-6% for natural gas boilers.

TREND ANALYSIS:
CO2 gradually rising over weeks without setting change → air filter blocking.
CO2 dropping suddenly → air damper opened, air intake unblocked, or flue leak.
        """
    },

    {
        "id": "guide_draft_pressure",
        "title": "How to Interpret Chimney Draft Pressure",
        "content": """
Draft pressure is the negative suction pressure inside the chimney.
It pulls combustion gases upward and out. Always negative during operation.

READING INTERPRETATION:
- -2 to -5 Pa: Normal operating draft
- -1 to -2 Pa: Mild restriction — inspect chimney soon
- 0 Pa: No draft — blocked or severe downdraught — SHUT DOWN
- -5 to -10 Pa: Excessive draft — too much cold air being pulled through
- Positive: Back pressure — flue gases reversing into boiler room — EVACUATE

RELATIONSHIP WITH FLUE TEMPERATURE:
Draft and flue temperature are related. Higher flue temperature = better natural draft
because hot gases are more buoyant. If flue temp drops, draft may also drop.

SEASONAL VARIATION:
Draft is stronger in winter (cold outside air is denser, more buoyant effect).
In summer, draft may be 0.5-1 Pa weaker — normal seasonal variation.
        """
    },

    {
        "id": "guide_water_level",
        "title": "Boiler Drum Water Level — Interpretation and Control",
        "content": """
Drum water level indicates how much water is available for steam generation.
Normal range: 40-60%. Measured as percentage of drum height.

READING INTERPRETATION:
- Above 60%: High level — risk of water carryover into steam pipes
  (wet steam damages steam equipment and pipework)
- 40-60%: Normal operating range
- 30-40%: LOW WARNING — check feed water pump immediately
- Below 30%: CRITICAL — shut down burner without delay
- Below 20%: EMERGENCY — do not add water, shut down and call engineer

CONTROL:
Level is maintained by the feed water control valve (automatic) or manually.
If level is falling: verify feed pump is running, check control valve is open.
If level is rising: reduce feed pump speed or throttle feed valve.

SWELL AND SHRINK:
When steam demand suddenly increases, water level temporarily RISES
(swell) — steam bubbles form inside water, expanding apparent volume.
This is normal. Level will settle within 2-3 minutes.
When steam demand suddenly drops, level temporarily FALLS (shrink) — normal.
        """
    },
]
```

---

## Step 2.2 — Index knowledge base into ChromaDB

Create `knowledge_base/indexer.py`:

```python
"""
Indexes all knowledge base documents into ChromaDB.
Run once before starting the chatbot.
Re-run whenever you add new documents to boiler_guides.py.
"""

import chromadb
from chromadb.utils import embedding_functions
from boiler_guides import KNOWLEDGE_DOCUMENTS
import os

CHROMA_PATH = "../chroma_db"

print("🔧 Initialising ChromaDB...")
embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"  # free, 22MB, runs locally
)

client = chromadb.PersistentClient(path=CHROMA_PATH)

# Delete and rebuild collection (clean slate)
try:
    client.delete_collection("boiler_knowledge")
    print("🗑️  Cleared existing collection")
except Exception:
    pass

collection = client.create_collection(
    name="boiler_knowledge",
    embedding_function=embedding_fn,
    metadata={"hnsw:space": "cosine"}
)

docs, ids, metas = [], [], []
for doc in KNOWLEDGE_DOCUMENTS:
    docs.append(doc["content"].strip())
    ids.append(doc["id"])
    metas.append({"title": doc["title"]})

collection.add(documents=docs, ids=ids, metadatas=metas)

print(f"✅ Indexed {len(docs)} knowledge documents")
print("   Topics covered:")
for doc in KNOWLEDGE_DOCUMENTS:
    print(f"   - {doc['title']}")
```

```bash
cd knowledge_base
pip install chromadb sentence-transformers
python indexer.py
```

---

---

# PART 3 — FINE-TUNING WITH LoRA (Day 5)

## Why fine-tune on top of RAG

RAG gives the model the right *information*. Fine-tuning gives it the right *reasoning style*. After fine-tuning, the model:

- Automatically identifies which fault a set of readings points to
- Knows the severity hierarchy (CRITICAL vs WARNING vs NORMAL)
- Responds in the structured format: Diagnosis → Cause → Action → Prevention
- Understands boiler-specific relationships (pressure + water level → double critical)

## Step 3.1 — Generate fine-tuning dataset

This JSONL exporter generates **boundary-covering** pairs — not random snapshots, but deliberately crafted examples across the full range of every sensor and fault combination.

Create `exporters/jsonl_exporter_v2.py`:

```python
"""
JSONL Exporter v2 — generates a comprehensive fine-tuning dataset.
Combines:
  1. Systematic boundary-covering sensor reading pairs
  2. Real fault history from InfluxDB
  3. Multi-sensor diagnostic pairs
  4. Predictive scenario pairs

Target: 500-1000 high-quality pairs (quality beats quantity for fine-tuning)
"""

import json, os
from influxdb_client import InfluxDBClient
from datetime import datetime

INFLUX_URL    = "http://localhost:8086"
INFLUX_TOKEN  = "my-super-secret-token-123"
INFLUX_ORG    = "boiler_org"
INFLUX_BUCKET = "boiler_data"
OUTPUT_FILE   = "data/train.jsonl"

client    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
query_api = client.query_api()

def qa(user: str, assistant: str) -> dict:
    return {"messages": [
        {"role": "user",      "content": user},
        {"role": "assistant", "content": assistant},
    ]}

def generate_pairs() -> list:
    pairs = []

    # ── 1. Boundary-covering sensor pairs ────────────────────────
    # These cover NORMAL, WARNING, and CRITICAL for every sensor
    sensor_scenarios = [
        # (sensor_name, value, unit, status, diagnosis, action)
        ("boiler pressure", 12.0, "bar", "NORMAL",
         "Boiler pressure is 12.0 bar, which is within the normal operating range of 10–14 bar. No action required.",
         "Continue normal operation. Monitor pressure trend."),

        ("boiler pressure", 14.5, "bar", "WARNING",
         "Boiler pressure is 14.5 bar, which has exceeded the normal maximum of 14 bar. This is a WARNING condition indicating the early stages of HIGH_PRESSURE fault.",
         "Reduce burner firing rate by 15% immediately. Check that downstream steam outlet valves are fully open. Monitor pressure — if not decreasing within 5 minutes, shut down burner."),

        ("boiler pressure", 18.2, "bar", "CRITICAL",
         "Boiler pressure is 18.2 bar — this is 29% above the critical threshold of 14 bar. HIGH_PRESSURE CRITICAL fault. Most likely cause: pressure relief valve stuck closed, or downstream steam outlet blocked.",
         "IMMEDIATE: Shut off burner. Manually test pressure relief valve by lifting test lever. Open steam outlet valves to release pressure. Do not restart until root cause identified."),

        ("boiler water level", 52.0, "%", "NORMAL",
         "Boiler drum water level is 52%, which is within the normal operating range of 40–60%.",
         "Normal. Feed water control is functioning correctly."),

        ("boiler water level", 35.0, "%", "WARNING",
         "Boiler drum water level is 35%, which has dropped below the safe minimum of 40%. LOW_WATER_LEVEL WARNING.",
         "Check feed water pump is running. Verify feed water control valve is open. Increase feed water supply immediately. If level continues dropping, shut off burner."),

        ("boiler water level", 22.0, "%", "CRITICAL",
         "Boiler drum water level is 22% — CRITICAL LOW_WATER_LEVEL fault. This is the most dangerous boiler condition. Running dry will overheat and rupture tubes.",
         "SHUT OFF BURNER IMMEDIATELY. Do not add cold water to hot boiler. Inspect feed water pump and valve. Call qualified engineer. Do not restart until level is above 40% and cause identified."),

        ("chimney CO", 25.0, "ppm", "NORMAL",
         "Chimney carbon monoxide is 25 ppm, within the normal range of 0–50 ppm. Combustion is complete.",
         "Normal combustion. No action required."),

        ("chimney CO", 75.0, "ppm", "WARNING",
         "Chimney CO is 75 ppm, which exceeds the 50 ppm threshold. HIGH_CO WARNING. Incomplete combustion is occurring.",
         "Increase combustion air supply — open air damper by 10%. Measure O2 in flue gas. Target O2: 3–8%. If CO does not reduce within 10 minutes of adding air, inspect burner nozzle for fouling."),

        ("chimney CO", 220.0, "ppm", "CRITICAL",
         "Chimney CO is 220 ppm — CRITICAL HIGH_CO fault. This level presents a personnel safety risk. Boiler room must be ventilated immediately.",
         "EVACUATE boiler room if personnel present. Open all ventilation. Shut down boiler if CO does not decrease within 5 minutes. Inspect burner nozzle, air filter, and heat exchanger for cracks."),

        ("chimney draft pressure", -3.5, "Pa", "NORMAL",
         "Chimney draft pressure is -3.5 Pa, within the normal range of -2 to -5 Pa. Good draft is pulling combustion gases out effectively.",
         "Normal. No action required."),

        ("chimney draft pressure", -0.8, "Pa", "WARNING",
         "Chimney draft pressure is -0.8 Pa, which is insufficient. Normal draft should be -2 to -5 Pa. BLOCKED_FLUE WARNING.",
         "Shut down boiler. Inspect chimney outlet for obstructions. Measure draft at multiple heights to locate blockage. Schedule chimney sweep. Do not operate with insufficient draft — CO back-flow risk."),

        ("chimney flue temperature", 200.0, "°C", "NORMAL",
         "Chimney flue gas temperature is 200°C, within the normal range of 150–250°C. Heat exchange is efficient.",
         "Normal operation. Boiler efficiency is good."),

        ("chimney flue temperature", 285.0, "°C", "WARNING",
         "Chimney flue temperature is 285°C, which exceeds the 250°C threshold. HIGH_FLUE_TEMP fault. The heat exchanger is not transferring heat efficiently to the water.",
         "Check O2 percentage — if above 8%, reduce excess air. Inspect flue baffles inside boiler. If flue temp has been rising gradually over weeks, scale buildup on heat exchanger is likely — schedule descaling treatment."),
    ]

    for scenario in sensor_scenarios:
        sensor, value, unit, status, diagnosis, action = scenario
        pairs.append(qa(
            f"The {sensor} is reading {value} {unit}. What does this mean and what should I do?",
            f"{diagnosis}\n\nAction: {action}"
        ))
        pairs.append(qa(
            f"Is {value} {unit} a safe {sensor} reading?",
            f"{'Yes — ' if status == 'NORMAL' else 'No — '}{diagnosis}"
        ))

    # ── 2. Fault explanation pairs ────────────────────────────────
    fault_explanations = [
        ("HIGH_PRESSURE", "CRITICAL",
         "HIGH_PRESSURE fault occurs when boiler steam pressure exceeds 14 bar. "
         "Most common causes: (1) pressure relief valve stuck closed, (2) downstream steam outlet blocked, "
         "(3) burner over-firing beyond steam demand. "
         "Immediate action: reduce burner rate, test relief valve, open steam outlets. "
         "Do not operate above 16 bar under any circumstances."),

        ("LOW_WATER_LEVEL", "CRITICAL",
         "LOW_WATER_LEVEL fault occurs when drum water level drops below 40%. "
         "Most common causes: (1) feed water pump failure, (2) feed water control valve stuck closed, "
         "(3) high steam demand exceeding supply. "
         "IMMEDIATELY shut off burner. Do not add cold water to hot boiler. "
         "Running a boiler dry causes tube overheating, warping, and potential explosion."),

        ("HIGH_CO", "CRITICAL",
         "HIGH_CO fault occurs when flue gas carbon monoxide exceeds 50 ppm. "
         "Caused by incomplete combustion — insufficient air reaching the burner. "
         "At 200+ ppm, evacuate boiler room — CO poisoning risk. "
         "Fix: increase combustion air, inspect burner nozzle and air filter."),

        ("BLOCKED_FLUE", "CRITICAL",
         "BLOCKED_FLUE fault occurs when chimney draft pressure is less negative than -2 Pa. "
         "Caused by soot buildup, physical obstruction, or structural collapse inside chimney. "
         "Do not operate with blocked flue — combustion gases including CO will back-flow into boiler room. "
         "Shut down and schedule professional chimney inspection."),

        ("HIGH_FLUE_TEMP", "WARNING",
         "HIGH_FLUE_TEMPERATURE fault occurs when chimney outlet temperature exceeds 250°C. "
         "Primary cause: scale or deposit buildup on boiler heat exchanger reducing heat transfer. "
         "Every 10°C above optimal flue temperature costs approximately 1% fuel efficiency. "
         "Action: check excess air level, inspect baffles, schedule descaling."),

        ("ABNORMAL_CO2", "WARNING",
         "ABNORMAL_CO2 fault on chimney indicates combustion mixture is out of balance. "
         "CO2 above 14%: insufficient air — increase air supply, risk of CO production. "
         "CO2 below 8%: excessive air — too much cold air, efficiency loss. "
         "Target CO2: 10-13% with O2 at 3-8% for efficient, safe combustion."),
    ]

    for fault_code, severity, explanation in fault_explanations:
        pairs.append(qa(f"What is a {fault_code} fault?", explanation))
        pairs.append(qa(f"Why does {fault_code} fault happen?", explanation))
        pairs.append(qa(f"How serious is {fault_code}?",
                        f"{fault_code} is a {severity} severity fault. {explanation}"))
        pairs.append(qa(f"How do I fix a {fault_code} fault?", explanation))

    # ── 3. Predictive scenario pairs ─────────────────────────────
    predictive_pairs = [
        (
            "Boiler pressure is currently 12.8 bar and has been rising at 0.3 bar every 10 minutes. What will happen and what should I do now?",
            "At the current rate of 0.3 bar per 10 minutes, boiler pressure will reach the critical threshold of 14 bar in approximately 4 minutes. "
            "This is a predictive HIGH_PRESSURE alert. Immediate action: reduce burner firing rate by 20% now, before reaching the critical threshold. "
            "Check if steam demand has dropped downstream — reduced demand with unchanged burner rate causes pressure rise. "
            "Monitor for 5 minutes after adjustment. If pressure continues rising despite reduced burner, suspect blocked outlet or faulty relief valve."
        ),
        (
            "Water level has been dropping from 55% to 48% over the last 20 minutes. Is this a problem?",
            "Water level dropping 7% over 20 minutes (0.35% per minute) is a WARNING trend. "
            "At this rate, level will reach the critical threshold of 40% in approximately 23 minutes. "
            "Action now: verify feed water pump is running and delivering water. "
            "Check feed water control valve is not stuck partially closed. "
            "If level is dropping due to high steam demand, consider reducing load or increasing pump speed. "
            "Set a manual watch — if level drops below 45%, increase feed rate urgently."
        ),
        (
            "Flue temperature has been increasing by 5°C every week for the past month. What does this indicate?",
            "A gradual flue temperature increase of 5°C per week over a month (approximately 20°C total) is a classic indicator of scale buildup on the boiler heat exchanger. "
            "As scale accumulates on tube surfaces, it acts as an insulator — heat from combustion cannot transfer to the water efficiently, so more heat exits through the chimney instead. "
            "This is not yet a critical fault but represents approximately 2% efficiency loss, wasting fuel. "
            "Recommended action: schedule chemical descaling treatment within 2-4 weeks. "
            "Also check: O2 percentage has not changed (rules out air ratio change as cause)."
        ),
        (
            "CO2 in the flue has gradually increased from 11% to 13.5% over the last hour. What should I check?",
            "CO2 rising from 11% to 13.5% over an hour indicates a gradual reduction in combustion air reaching the burner. "
            "Most likely cause: air intake filter becoming blocked with dust over time. "
            "This is still within acceptable range (below 14% threshold) but is trending toward HIGH_CO2 fault. "
            "Immediate check: inspect combustion air filter — if visibly dirty, replace or clean. "
            "Also verify air damper position has not changed. "
            "After cleaning filter, CO2 should return to 10-12% range."
        ),
    ]

    for user, assistant in predictive_pairs:
        pairs.append(qa(user, assistant))

    # ── 4. Real fault history from InfluxDB ───────────────────────
    try:
        query = f"""
        from(bucket: "{INFLUX_BUCKET}")
          |> range(start: -7d)
          |> filter(fn: (r) => r["_measurement"] == "fault_events")
          |> filter(fn: (r) => r["_field"] == "message")
          |> sort(columns: ["_time"], desc: true)
        """
        tables = query_api.query(query)
        real_faults = []
        for table in tables:
            for record in table.records:
                real_faults.append({
                    "fault_code": record.values.get("fault_code"),
                    "severity":   record.values.get("severity"),
                    "sensor":     record.values.get("sensor", ""),
                    "time":       str(record.get_time()),
                    "message":    record.get_value(),
                })

        if real_faults:
            # Most recent fault pair
            latest = real_faults[0]
            pairs.append(qa(
                "What was the most recent fault on this system?",
                f"The most recent fault was [{latest['severity']}] {latest['fault_code']} "
                f"detected on sensor '{latest['sensor']}' at {latest['time']}. "
                f"Details: {latest['message']}"
            ))
            # Fault count summary
            from collections import Counter
            fault_counts = Counter(f["fault_code"] for f in real_faults)
            summary = ", ".join([f"{code}: {count} times" for code, count in fault_counts.most_common(5)])
            pairs.append(qa(
                "Which fault has occurred most frequently?",
                f"In the last 7 days, fault frequency was: {summary}. "
                f"Total fault events: {len(real_faults)}."
            ))

    except Exception as e:
        print(f"⚠️  Could not fetch InfluxDB fault history: {e}")

    return pairs


# ── MAIN ─────────────────────────────────────────────────────────
os.makedirs("data", exist_ok=True)
print("📊 Generating fine-tuning dataset...")
pairs = generate_pairs()

with open(OUTPUT_FILE, "w") as f:
    for pair in pairs:
        f.write(json.dumps(pair) + "\n")

print(f"✅ Generated {len(pairs)} training pairs → {OUTPUT_FILE}")
print(f"   Breakdown:")
print(f"   - Sensor boundary pairs: ~{len(sensor_scenarios)*2}")
print(f"   - Fault explanation pairs: ~{len(fault_explanations)*4}")
print(f"   - Predictive scenario pairs: {len(predictive_pairs)}")
```

---

## Step 3.2 — Fine-tune Mistral 7B with LoRA

Create `training/fine_tune.py`:

```python
"""
Fine-tuning script — Mistral 7B + QLoRA (4-bit).
Requires GPU with 16GB VRAM (RTX 3090, A100) or Google Colab T4.
"""

import json, torch
from datasets import Dataset
from transformers import (
    AutoModelForCausalLM, AutoTokenizer,
    TrainingArguments, BitsAndBytesConfig,
)
from peft import get_peft_model, LoraConfig, TaskType, prepare_model_for_kbit_training
from trl import SFTTrainer

BASE_MODEL = "mistralai/Mistral-7B-Instruct-v0.2"
TRAIN_FILE = "../data/train.jsonl"
OUTPUT_DIR = "../models/boiler_mistral_lora"

# Load and format dataset
def load_and_format(filepath):
    records = []
    with open(filepath) as f:
        for line in f:
            item = json.loads(line.strip())
            msgs = item["messages"]
            user = next(m["content"] for m in msgs if m["role"] == "user")
            asst = next(m["content"] for m in msgs if m["role"] == "assistant")
            # Mistral instruction format
            records.append({"text": f"<s>[INST] {user} [/INST] {asst} </s>"})
    return Dataset.from_list(records)

dataset = load_and_format(TRAIN_FILE).train_test_split(test_size=0.1)
print(f"✅ Dataset: {len(dataset['train'])} train / {len(dataset['test'])} eval")

# 4-bit quantization config (QLoRA)
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
)

tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
tokenizer.pad_token = tokenizer.eos_token

model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    quantization_config=bnb_config,
    device_map="auto",
)
model = prepare_model_for_kbit_training(model)

# LoRA config
lora_config = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
    bias="none",
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()
# → trainable params: ~4M / 7B total (0.06%)

training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,
    num_train_epochs=3,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    fp16=True,
    save_steps=50,
    logging_steps=10,
    evaluation_strategy="steps",
    eval_steps=50,
    warmup_steps=20,
    report_to="none",
)

trainer = SFTTrainer(
    model=model,
    args=training_args,
    train_dataset=dataset["train"],
    eval_dataset=dataset["test"],
    dataset_text_field="text",
    max_seq_length=512,
)

print("🚀 Fine-tuning started...")
trainer.train()
model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)
print(f"✅ Model saved → {OUTPUT_DIR}")
```

---

---

# PART 4 — RAG PIPELINE (full implementation)

## Step 4.1 — Core chatbot with fine-tuned model + RAG

Create `rag/chatbot.py`:

```python
"""
Production Boiler Chatbot
Combines: fine-tuned Mistral 7B (via Ollama) + ChromaDB RAG + InfluxDB real-time data
"""

import chromadb
from chromadb.utils import embedding_functions
from influxdb_client import InfluxDBClient
from ollama import Client as OllamaClient
from datetime import datetime
import time

# ── CONFIG ────────────────────────────────────────────────────────
INFLUX_URL    = "http://localhost:8086"
INFLUX_TOKEN  = "my-super-secret-token-123"
INFLUX_ORG    = "boiler_org"
INFLUX_BUCKET = "boiler_data"
CHROMA_PATH   = "./chroma_db"
OLLAMA_MODEL  = "boiler-mistral"    # your fine-tuned model served via Ollama

SENSOR_UNITS = {
    "temperature": "°C",   "pressure": "bar",
    "fuel_flow": "L/min",  "water_level": "%",
    "air_flow": "m³/h",    "flue_temp": "°C",
    "co2": "%",            "o2": "%",
    "co": "ppm",           "draft": "Pa",
    "stack_velocity": "m/s",
}
SENSOR_NORMAL = {
    "temperature": (60,100),   "pressure": (10,14),
    "fuel_flow": (5,20),       "water_level": (40,60),
    "air_flow": (100,300),     "flue_temp": (150,250),
    "co2": (8,14),             "o2": (3,8),
    "co": (0,50),              "draft": (-5,-2),
    "stack_velocity": (3,8),
}
# ─────────────────────────────────────────────────────────────────


class BoilerChatbot:

    def __init__(self):
        # InfluxDB
        self.influx    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        self.query_api = self.influx.query_api()

        # ChromaDB
        embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        chroma = chromadb.PersistentClient(path=CHROMA_PATH)
        self.collection = chroma.get_collection("boiler_knowledge", embedding_function=embed_fn)

        # Fine-tuned LLM via Ollama
        self.llm = OllamaClient()
        print("✅ Chatbot initialised")

    # ── Real-time data ─────────────────────────────────────────────

    def get_snapshot(self) -> dict:
        snapshot = {}
        configs = [
            ("boiler_sensors",  "BOILER_001",  ["temperature","pressure","fuel_flow","water_level","air_flow"]),
            ("chimney_sensors", "CHIMNEY_001", ["flue_temp","co2","o2","co","draft","stack_velocity"]),
        ]
        for measurement, device, sensors in configs:
            for sensor in sensors:
                q = f"""
                from(bucket: "{INFLUX_BUCKET}")
                  |> range(start: -5m)
                  |> filter(fn: (r) => r["_measurement"] == "{measurement}")
                  |> filter(fn: (r) => r["sensor"] == "{sensor}")
                  |> filter(fn: (r) => r["_field"] == "value")
                  |> last()
                """
                try:
                    for table in self.query_api.query(q):
                        for record in table.records:
                            snapshot[sensor] = {
                                "value": round(record.get_value(), 2),
                                "device": device,
                            }
                except Exception:
                    pass
        return snapshot

    def get_recent_faults(self, minutes: int = 60) -> list:
        q = f"""
        from(bucket: "{INFLUX_BUCKET}")
          |> range(start: -{minutes}m)
          |> filter(fn: (r) => r["_measurement"] == "fault_events")
          |> filter(fn: (r) => r["_field"] == "message")
          |> sort(columns: ["_time"], desc: true)
          |> limit(n: 10)
        """
        faults = []
        try:
            for table in self.query_api.query(q):
                for record in table.records:
                    faults.append({
                        "fault_code": record.values.get("fault_code"),
                        "severity":   record.values.get("severity"),
                        "sensor":     record.values.get("sensor", ""),
                        "time":       str(record.get_time()),
                        "message":    record.get_value(),
                    })
        except Exception:
            pass
        return faults

    def build_sensor_context(self, snapshot: dict, faults: list) -> str:
        lines = ["=== LIVE SENSOR READINGS (last 5 minutes) ==="]
        for sensor, data in snapshot.items():
            val  = data["value"]
            unit = SENSOR_UNITS.get(sensor, "")
            lo, hi = SENSOR_NORMAL.get(sensor, (None, None))
            if lo is not None:
                flag = "✅ NORMAL" if lo <= val <= hi else "⚠️  OUT OF RANGE"
            else:
                flag = ""
            lines.append(f"  {sensor:20s}: {val:8.2f} {unit:6s}  {flag}")

        lines.append(f"\n=== FAULT EVENTS (last 60 min) ===")
        if faults:
            for f in faults[:5]:
                lines.append(f"  [{f['severity']:8s}] {f['fault_code']:25s} | sensor: {f['sensor']:20s} | {f['time']}")
        else:
            lines.append("  No faults in last 60 minutes")
        return "\n".join(lines)

    # ── Knowledge retrieval ────────────────────────────────────────

    def retrieve_knowledge(self, question: str, n: int = 3) -> str:
        results = self.collection.query(query_texts=[question], n_results=n)
        sections = []
        for title, doc in zip(results["metadatas"][0], results["documents"][0]):
            sections.append(f"--- {title['title']} ---\n{doc.strip()}")
        return "\n\n".join(sections)

    # ── Main answer ────────────────────────────────────────────────

    def answer(self, question: str) -> dict:
        start_time = time.time()

        snapshot    = self.get_snapshot()
        faults      = self.get_recent_faults()
        sensor_ctx  = self.build_sensor_context(snapshot, faults)
        knowledge   = self.retrieve_knowledge(question)

        prompt = f"""You are a senior industrial engineer specialising in boiler and chimney systems.

Your responsibilities:
- Diagnose faults based on real-time sensor data
- Predict what will go wrong if a trend continues
- Give specific, actionable fix instructions
- Explain WHY a fault is happening, not just WHAT it is
- Only use the sensor data and knowledge provided — do not guess

{sensor_ctx}

=== TECHNICAL KNOWLEDGE ===
{knowledge}

=== ENGINEER QUESTION ===
{question}

=== YOUR EXPERT DIAGNOSIS AND GUIDANCE ==="""

        response = self.llm.generate(model=OLLAMA_MODEL, prompt=prompt)
        answer_text = response["response"].strip()
        latency_ms  = round((time.time() - start_time) * 1000, 1)

        return {
            "answer":         answer_text,
            "latency_ms":     latency_ms,
            "sensor_snapshot": snapshot,
            "faults_found":   faults,
            "retrieved_docs": self.collection.query(
                query_texts=[question], n_results=3
            )["metadatas"][0],
            "context_used":   sensor_ctx,
            "knowledge_used": knowledge,
        }
```

---

---

# PART 5 — EVALUATION METRICS

## What you are measuring and why

After every chatbot answer you calculate four scores. These tell you exactly how accurate and trustworthy the chatbot is.

```
Score              Range   What it measures
──────────────────────────────────────────────────────────────────────
Faithfulness       0–1     Did the answer only use info from context?
                           0 = hallucinated freely, 1 = perfectly grounded
                           
Context Recall     0–1     Did the retrieved docs contain the answer?
                           0 = retrieved wrong docs, 1 = perfect retrieval
                           
Answer Relevancy   0–1     Does the answer address the actual question?
                           0 = completely off-topic, 1 = perfectly on-topic
                           
Latency            ms      How fast was the response?
                           Target: under 5000ms (5 seconds)
```

## Step 5.1 — Evaluation engine

Create `evaluation/evaluator.py`:

```python
"""
Evaluation Engine — measures chatbot answer quality after every query.
Uses RAGAS metrics (faithfulness, context recall, answer relevancy)
plus latency measurement.
Scores are stored in InfluxDB and visible in Grafana.
"""

from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_recall
from datasets import Dataset
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime
from langchain_community.llms import Ollama
from langchain_community.embeddings import HuggingFaceEmbeddings
import numpy as np

# ── CONFIG ────────────────────────────────────────────────────────
INFLUX_URL    = "http://localhost:8086"
INFLUX_TOKEN  = "my-super-secret-token-123"
INFLUX_ORG    = "boiler_org"
INFLUX_BUCKET = "boiler_data"
OLLAMA_MODEL  = "mistral"   # judge model (can be base mistral, not fine-tuned)
# ─────────────────────────────────────────────────────────────────

influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api     = influx_client.write_api(write_options=SYNCHRONOUS)


class BoilerEvaluator:

    def __init__(self):
        # RAGAS uses an LLM to judge faithfulness and relevancy
        self.judge_llm = Ollama(model=OLLAMA_MODEL, temperature=0)
        self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        print("✅ Evaluator initialised")

    def evaluate_answer(
        self,
        question:    str,
        answer:      str,
        contexts:    list,    # list of retrieved document strings
        latency_ms:  float,
        ground_truth: str = None,  # optional reference answer
    ) -> dict:
        """
        Run all evaluation metrics on one Q&A pair.
        Returns scores dict and logs them to InfluxDB.
        """

        # ── Build RAGAS evaluation dataset ───────────────────────
        eval_data = {
            "question":  [question],
            "answer":    [answer],
            "contexts":  [contexts],
        }
        if ground_truth:
            eval_data["ground_truth"] = [ground_truth]

        eval_dataset = Dataset.from_dict(eval_data)

        # ── Run RAGAS metrics ─────────────────────────────────────
        metrics_to_run = [faithfulness, answer_relevancy]
        if ground_truth:
            metrics_to_run.append(context_recall)

        try:
            result = evaluate(
                dataset=eval_dataset,
                metrics=metrics_to_run,
                llm=self.judge_llm,
                embeddings=self.embeddings,
            )
            scores = result.to_pandas().iloc[0].to_dict()
        except Exception as e:
            print(f"⚠️  RAGAS evaluation error: {e}")
            scores = {
                "faithfulness":     None,
                "answer_relevancy": None,
                "context_recall":   None,
            }

        # ── Compute simple context coverage score ────────────────
        # Did the answer mention keywords from the retrieved context?
        context_text = " ".join(contexts).lower()
        answer_words = set(answer.lower().split())
        context_words = set(context_text.split())
        overlap = len(answer_words & context_words)
        context_coverage = round(min(overlap / max(len(answer_words), 1), 1.0), 3)

        # ── Overall quality score (weighted average) ──────────────
        available = [
            v for v in [
                scores.get("faithfulness"),
                scores.get("answer_relevancy"),
                context_coverage,
            ] if v is not None
        ]
        overall = round(float(np.mean(available)), 3) if available else None

        final_scores = {
            "faithfulness":      round(float(scores.get("faithfulness", 0) or 0), 3),
            "answer_relevancy":  round(float(scores.get("answer_relevancy", 0) or 0), 3),
            "context_recall":    round(float(scores.get("context_recall", 0) or 0), 3) if ground_truth else None,
            "context_coverage":  context_coverage,
            "overall_quality":   overall,
            "latency_ms":        latency_ms,
            "timestamp":         datetime.utcnow().isoformat() + "Z",
        }

        # ── Log to InfluxDB ───────────────────────────────────────
        self._log_to_influx(question, final_scores)

        return final_scores

    def _log_to_influx(self, question: str, scores: dict):
        """Write evaluation scores to InfluxDB for Grafana dashboard."""
        point = (
            Point("chatbot_evaluation")
            .tag("question_preview", question[:50])
            .field("faithfulness",     scores["faithfulness"])
            .field("answer_relevancy", scores["answer_relevancy"])
            .field("context_coverage", scores["context_coverage"])
            .field("latency_ms",       scores["latency_ms"])
            .time(scores["timestamp"])
        )
        if scores.get("overall_quality") is not None:
            point = point.field("overall_quality", scores["overall_quality"])
        if scores.get("context_recall") is not None:
            point = point.field("context_recall", scores["context_recall"])

        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
        print(
            f"📊 Eval: faith={scores['faithfulness']:.2f} | "
            f"relevancy={scores['answer_relevancy']:.2f} | "
            f"latency={scores['latency_ms']}ms | "
            f"overall={scores.get('overall_quality', 'N/A')}"
        )
```

Install:
```bash
pip install ragas langchain-community
```

---

---

# PART 6 — FASTAPI — PRODUCTION CHATBOT API

Create `api/chatbot_api.py`:

```python
"""
Production FastAPI — Boiler Chatbot API
Endpoints:
  POST /chat          — ask a question, get answer + eval scores
  GET  /status        — real-time sensor snapshot + active faults
  GET  /metrics       — recent evaluation metric averages
  GET  /health        — service health check
  WS   /ws/chat       — WebSocket for streaming responses
"""

from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import sys, json
sys.path.append("..")

from rag.chatbot import BoilerChatbot
from evaluation.evaluator import BoilerEvaluator
from influxdb_client import InfluxDBClient

app = FastAPI(
    title="Boiler & Chimney AI Chatbot",
    description="Real-time industrial IoT chatbot with fault diagnosis and prediction",
    version="2.0"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialise once at startup
chatbot   = BoilerChatbot()
evaluator = BoilerEvaluator()

influx = InfluxDBClient(
    url="http://localhost:8086",
    token="my-super-secret-token-123",
    org="boiler_org"
)


class ChatRequest(BaseModel):
    question: str
    ground_truth: str = None    # optional reference answer for context_recall metric
    session_id: str = "default"

class ChatResponse(BaseModel):
    question:    str
    answer:      str
    latency_ms:  float
    eval_scores: dict
    timestamp:   str


@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """Main chat endpoint — returns answer + evaluation scores."""

    # Get answer from chatbot
    result = chatbot.answer(request.question)

    # Extract retrieved context strings for evaluation
    contexts = [
        doc.get("title", "") + ": " + result["knowledge_used"]
        for doc in result["retrieved_docs"]
    ]

    # Evaluate answer quality
    eval_scores = evaluator.evaluate_answer(
        question=request.question,
        answer=result["answer"],
        contexts=[result["knowledge_used"], result["context_used"]],
        latency_ms=result["latency_ms"],
        ground_truth=request.ground_truth,
    )

    return ChatResponse(
        question=request.question,
        answer=result["answer"],
        latency_ms=result["latency_ms"],
        eval_scores=eval_scores,
        timestamp=datetime.utcnow().isoformat(),
    )


@app.get("/status")
def status():
    """Returns live sensor readings and recent faults."""
    snapshot = chatbot.get_snapshot()
    faults   = chatbot.get_recent_faults(minutes=60)
    return {
        "sensors":   snapshot,
        "faults":    faults,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/metrics")
def metrics():
    """Returns average evaluation scores from the last 50 queries."""
    query = """
    from(bucket: "boiler_data")
      |> range(start: -24h)
      |> filter(fn: (r) => r["_measurement"] == "chatbot_evaluation")
      |> filter(fn: (r) => r["_field"] == "faithfulness" or
                           r["_field"] == "answer_relevancy" or
                           r["_field"] == "latency_ms" or
                           r["_field"] == "overall_quality")
      |> mean()
    """
    try:
        tables = influx.query_api().query(query)
        averages = {}
        for table in tables:
            for record in table.records:
                averages[record.get_field()] = round(record.get_value(), 3)
        return {"averages_last_24h": averages, "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket for real-time streaming chat."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            request = json.loads(data)
            question = request.get("question", "")
            result = chatbot.answer(question)
            await websocket.send_json({
                "answer":     result["answer"],
                "latency_ms": result["latency_ms"],
                "timestamp":  datetime.utcnow().isoformat(),
            })
    except Exception:
        pass
```

Run:
```bash
uvicorn api.chatbot_api:app --host 0.0.0.0 --port 8000 --reload
```

API docs auto-generated at `http://localhost:8000/docs`

---

---

# PART 7 — GRAFANA EVALUATION DASHBOARD

Since you already have Grafana set up, add these panels to a new dashboard called **"Chatbot Quality Metrics"**.

## Panel 1 — Overall Quality Score (Gauge)

```flux
from(bucket: "boiler_data")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "chatbot_evaluation")
  |> filter(fn: (r) => r["_field"] == "overall_quality")
  |> mean()
```
Visualization: **Gauge** | Min: 0 | Max: 1 | Thresholds: 0-0.5 red, 0.5-0.75 yellow, 0.75-1.0 green

## Panel 2 — Faithfulness Over Time (Time Series)

```flux
from(bucket: "boiler_data")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "chatbot_evaluation")
  |> filter(fn: (r) => r["_field"] == "faithfulness" or
                       r["_field"] == "answer_relevancy" or
                       r["_field"] == "context_coverage")
```
Visualization: **Time series** (shows all three lines together)

## Panel 3 — Response Latency (Time Series)

```flux
from(bucket: "boiler_data")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "chatbot_evaluation")
  |> filter(fn: (r) => r["_field"] == "latency_ms")
```
Visualization: **Time series** | Unit: milliseconds | Alert if > 8000ms

## Panel 4 — Score Averages Table (Stat panels)

Create 4 separate **Stat** panels:
- Faithfulness (last 24h avg) — target > 0.80
- Answer Relevancy (last 24h avg) — target > 0.85
- Context Coverage (last 24h avg) — target > 0.75
- Avg Latency (last 24h avg) — target < 4000ms

---

---

# PART 8 — COMPLETE STARTUP SEQUENCE

```bash
#!/bin/bash
# start_complete_system.sh

echo "═══════════════════════════════════════════"
echo "  Boiler AI System — Full Startup"
echo "═══════════════════════════════════════════"

# 1. Infrastructure
echo "▶ Starting Docker services..."
docker-compose up -d emqx influxdb grafana
sleep 10

# 2. Serve fine-tuned LLM
echo "▶ Serving fine-tuned model via Ollama..."
ollama serve &
sleep 5

# 3. Index knowledge base (safe to re-run)
echo "▶ Indexing knowledge base..."
cd knowledge_base && python indexer.py && cd ..

# 4. Start simulators
echo "▶ Starting simulators..."
python simulators/boiler_simulator.py &
python simulators/chimney_simulator.py &

# 5. Start consumers
echo "▶ Starting data consumers..."
python consumers/influx_consumer.py &
python consumers/fault_detector.py &

# 6. Start chatbot API
echo "▶ Starting chatbot API..."
uvicorn api.chatbot_api:app --host 0.0.0.0 --port 8000

echo "═══════════════════════════════════════════"
echo "  Services running:"
echo "  Grafana:       http://localhost:3000"
echo "  EMQX:          http://localhost:18083"
echo "  InfluxDB:      http://localhost:8086"
echo "  Chatbot API:   http://localhost:8000"
echo "  API Docs:      http://localhost:8000/docs"
echo "═══════════════════════════════════════════"
```

---

---

# PART 9 — FINAL PROJECT FOLDER STRUCTURE

```
boiler-iot-system/
│
├── docker-compose.yml
│
├── config.py                          ← MODE=simulation|production
│
├── simulators/
│   ├── boiler_simulator.py            ✅ done
│   └── chimney_simulator.py           ✅ done
│
├── consumers/
│   ├── influx_consumer.py             ✅ done
│   └── fault_detector.py             ✅ done
│
├── knowledge_base/
│   ├── boiler_guides.py               ← Part 2 — fault + sensor docs
│   └── indexer.py                     ← indexes into ChromaDB
│
├── exporters/
│   └── jsonl_exporter_v2.py           ← Part 3 — boundary-covering dataset
│
├── data/
│   └── train.jsonl                    ← generated training data
│
├── training/
│   └── fine_tune.py                   ← Part 3 — LoRA fine-tuning
│
├── models/
│   └── boiler_mistral_lora/           ← saved LoRA adapter
│
├── chroma_db/                         ← ChromaDB vector store (auto-created)
│
├── rag/
│   └── chatbot.py                     ← Part 4 — fine-tuned + RAG pipeline
│
├── evaluation/
│   └── evaluator.py                   ← Part 5 — RAGAS metrics + InfluxDB logging
│
├── api/
│   └── chatbot_api.py                 ← Part 6 — FastAPI endpoints
│
├── start_complete_system.sh           ← one-command startup
└── requirements.txt
```

---

# PART 10 — REQUIREMENTS

```
# Core IoT
paho-mqtt==1.6.1
influxdb-client==1.36.1

# LLM + Fine-tuning
transformers==4.38.0
peft==0.8.0
trl==0.8.1
datasets==2.17.0
accelerate==0.27.0
bitsandbytes==0.42.0
torch==2.2.0

# RAG + Vector DB
chromadb==0.4.22
sentence-transformers==2.3.1
ollama==0.1.7
langchain==0.1.9
langchain-community==0.0.24

# Evaluation
ragas==0.1.7
numpy==1.26.4

# API
fastapi==0.109.2
uvicorn==0.27.1
websockets==12.0
```

---

## 📊 What "Good" Evaluation Scores Look Like

| Metric | Poor | Acceptable | Good | Target |
|---|---|---|---|---|
| Faithfulness | < 0.5 | 0.5–0.7 | 0.7–0.85 | **> 0.85** |
| Answer Relevancy | < 0.6 | 0.6–0.75 | 0.75–0.9 | **> 0.85** |
| Context Coverage | < 0.4 | 0.4–0.6 | 0.6–0.8 | **> 0.70** |
| Latency | > 10s | 5–10s | 2–5s | **< 4s** |
| Overall Quality | < 0.5 | 0.5–0.7 | 0.7–0.85 | **> 0.80** |

If faithfulness is low → model is hallucinating. Improve the prompt or add more context.
If relevancy is low → model is answering a different question. Improve retrieval (add more knowledge docs).
If latency is high → Ollama hardware is the bottleneck. Use a smaller model (Phi-3 Mini) or reduce max_tokens.

---

*Stack: Python · MQTT · EMQX · InfluxDB · Grafana · Mistral 7B · LoRA · QLoRA · ChromaDB · LangChain · RAGAS · FastAPI · Ollama · Docker*