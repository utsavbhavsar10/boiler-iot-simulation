# Boiler IoT Agentic RAG — Project Overview

A briefing document for supervisor review. Explains **what** the system is,
**why** each architectural choice was made, and the reasoning behind the
tools, orchestrator, and UI design.

---

## 1. Problem Statement

Thermal power plants run boilers, turbines and chimneys that are monitored
by dozens of sensors (pressure, temperature, flow, oxygen, draft, CO, etc.).
Operators need to answer questions like:

- *Is the boiler safe right now?*
- *Why is feedwater pressure dropping?*
- *Will flue gas temperature breach the limit in the next hour?*
- *What faults have occurred in the last 60 minutes?*

A traditional dashboard shows raw numbers but cannot **diagnose**, **explain
the root cause**, or **predict** failures. A plain LLM chatbot, on the other
hand, hallucinates — it has no access to the live plant.

**Goal:** a chatbot that is grounded in real-time plant data, follows Indian
Boiler Regulations (IBR) standards, and explains its reasoning step by step.

---

## 2. High-Level Architecture

```
┌──────────────┐     MQTT      ┌──────────────┐    Influx     ┌──────────────┐
│  Simulators  │ ────────────▶ │  Subscriber  │ ────────────▶ │   InfluxDB   │
│ (publisher/) │               │ (consumers/) │               │ (time series)│
└──────────────┘               └──────────────┘               └──────┬───────┘
                                                                     │
                                                                     ▼
┌──────────────┐    SSE / HTTP   ┌──────────────┐   tool calls   ┌──────────────┐
│  Streamlit   │ ◀────────────── │   FastAPI    │ ─────────────▶ │ Orchestrator │
│     UI       │                 │   /chat      │                │ (ReAct loop) │
└──────────────┘                 └──────────────┘                └──────┬───────┘
                                                                       │
                                          ┌────────────────────────────┼────────────────────────────┐
                                          ▼                            ▼                            ▼
                                ┌───────────────────┐       ┌───────────────────┐       ┌───────────────────┐
                                │ fetch_realtime_   │       │ get_fault_history │       │  predict_trend    │
                                │     sensors       │       │                   │       │                   │
                                └───────────────────┘       └───────────────────┘       └───────────────────┘
                                          │                            │                            │
                                          └──────────── InfluxDB ──────┴────────────────────────────┘

                                Fine-tuned Gemini 2.5 Flash (Vertex AI)
                                drives the ReAct loop with function calling.
```

Data flow: simulators publish MQTT → consumer writes to InfluxDB → tools
read from InfluxDB → orchestrator feeds tool results back into the
fine-tuned Gemini model → UI streams the answer + tool-call trace.

---

## 3. Why Agentic RAG (and not plain RAG or a plain LLM)?

| Approach          | Problem                                                                 |
| ----------------- | ----------------------------------------------------------------------- |
| Plain LLM         | No live data → confidently hallucinates numbers and faults.             |
| Plain RAG (docs)  | Retrieves manuals but cannot answer "what is happening **right now**?". |
| **Agentic RAG**   | LLM decides *which live tool to call* per question, then synthesises.   |

The plant state is dynamic. A static vector DB cannot answer *"is feedwater
pressure within IBR limits at this instant?"* — that requires a live query.
Agentic RAG lets the model **choose** between a real-time sensor read, a
fault-history query, and a trend prediction, based on what the user asked.

---

## 4. Why a Fine-tuned Gemini 2.5 Flash?

- **Domain language.** Boiler/chimney terminology, IBR thresholds, fault
  codes (`HIGH_MAIN_STEAM_PRESSURE`, `LOW_DRAFT`, …) are niche. Fine-tuning
  on labelled diagnosis examples teaches the model the correct vocabulary,
  the correct structure of an engineering answer, and the right severity
  framing.
- **Tool-calling reliability.** A fine-tuned model picks the *right* tool
  more often than a generic one for this domain — e.g. it learns that
  "will it breach" implies `predict_trend`, not `fetch_realtime_sensors`.
- **Cost / latency.** Flash is small enough to keep `/chat/stream`
  responsive (sub-second to first token in normal cases), and cheap enough
  for continuous operator use.
- **Deployed on Vertex AI** for managed scaling and the same
  function-calling API used in training.

Generation knobs (`assistant/config.py`):
- `temperature = 0.1` — factual, not creative.
- `top_p = 0.8` — keeps token choices tight.
- `max_output_tokens = 1024` — enough for a full diagnosis, not so much
  that the model rambles.

---

## 5. Why the ReAct Orchestrator?

The orchestrator (`assistant/agent/orchestrator.py`,
`BoilerAgentOrchestrator`) implements the classic **Re**ason +
**Act** loop with Gemini function calling:

```
loop (up to MAX_AGENT_STEPS):
    model.generate_content(conversation, tools=[BOILER_AGENT_TOOLS])
    if response contains tool_call:
        execute the Python function
        append result to conversation
        continue
    elif response contains final text:
        return as the answer
```

### Why ReAct over a single-shot call?

- **Multi-step reasoning.** Diagnosing "why is pressure low?" often needs
  *both* the current reading *and* the last hour of faults. ReAct lets the
  model fetch one, see the result, then decide whether to fetch the next.
- **Transparency.** Every tool call, its arguments, and its result are
  logged into `steps`. This becomes the audit trail shown in the UI
  expander — supervisors and operators can verify *what data the model
  used* to make its claim.
- **Bounded.** `MAX_AGENT_STEPS = 6` caps runaway loops.

### Why a single dispatcher (`TOOL_REGISTRY`)?

A simple `{tool_name: python_function}` dict makes adding new tools
trivial and avoids dynamic imports / reflection. `execute_tool()` wraps
every call in a try/except and **never raises** — failures are returned to
Gemini as `"ERROR: …"` text, so the model can recover or apologise instead
of crashing the HTTP request.

### Why two entry points: `run()` and `run_stream()`?

- `run()` — synchronous; used by tests, the legacy `/chat` endpoint, and
  the WebSocket handler.
- `run_stream()` — generator that yields `tool_start`, `tool_end`,
  `answer_chunk`, `done`, `error` events so the UI can render the
  ChatGPT-style live progress. Same ReAct logic, just instrumented.

---

## 6. Why These Three Tools (and only these)?

The tool set is intentionally small. Each tool answers a distinct question
the model cannot answer on its own.

### 6.1 `fetch_realtime_sensors`  — *"What is happening right now?"*

- Reads the latest point per sensor from InfluxDB (boiler, turbine,
  chimney measurements).
- Compares each value against `SENSOR_NORMAL_RANGE` and
  `SENSOR_CRITICAL_RANGE` from `config.py` and labels every reading as
  `NORMAL`, `WARNING`, or `CRITICAL`.
- Returns a formatted string the model can read directly — already
  enriched with thresholds and units, so the model does not have to
  guess what is "normal".

**Why this design:** the tool does the *threshold comparison* in Python,
not the LLM. Numerical comparison is exactly what LLMs are bad at and
Python is good at. The model is left to do the *reasoning*, not the
arithmetic.

### 6.2 `get_fault_history`  — *"What has gone wrong recently?"*

- Queries the `faults` measurement in InfluxDB for the last *N* minutes
  (default 60).
- Groups by fault code, severity, and timestamp.

**Why a separate tool:** real-time readings only show the *current* state.
A momentarily-normal sensor can have been alarming five minutes ago, and
that history is essential for root-cause analysis (e.g. recurring
`LOW_DRAFT` → blocked flue). Keeping fault history as its own tool means
the model only pays the query cost when the question actually needs it.

### 6.3 `predict_trend`  — *"What is about to happen?"*

- Pulls the recent time-series for a chosen sensor and fits a simple
  linear projection toward its critical threshold.
- Returns: current value, slope, threshold, predicted time-to-breach.

**Why this design:** prediction is delegated to a deterministic numerical
routine, not the LLM. The model decides *which* sensor to project
(based on the question), but the projection itself is reproducible
arithmetic. This is the "ground-truth" core of every "will it breach?"
answer.

### Tools deliberately *not* included

- **`search_knowledge_base`** (vector RAG over manuals) — scaffolded but
  disabled. Reason: the manuals overlap heavily with what the fine-tuned
  model already knows about IBR. Re-enabling is a config flip when the
  manual corpus grows large enough to matter.
- **Mutation tools** (write setpoints, acknowledge alarms) —
  intentionally excluded. A chatbot must not change plant state.

---

## 7. Why the FastAPI Layer Looks the Way It Does

- **`POST /chat`** — synchronous, returns the whole answer + steps. Easy
  to call from tests, scripts, and other backends.
- **`POST /chat/stream`** — Server-Sent Events (SSE). Chosen over
  WebSocket because:
  - SSE is one-way (server → client), which matches our need.
  - It works through HTTP proxies without special config.
  - `fetch`/`requests` clients can consume it line-by-line.
- **`GET /status`** — separates the live sensor snapshot from the chat
  flow so the dashboard can poll cheaply without invoking the LLM.
- **`GET /health`** — used by the sidebar status pill.
- **`/ws/chat`** WebSocket — kept for backward compatibility.

CORS is open for the Streamlit UI; in production this would be locked
down to the operator portal origin.

---

## 8. Why the UI Was Redesigned ChatGPT/Claude-style

Operators are familiar with conversational AI from consumer tools. The
new Streamlit UI mirrors those patterns to lower the learning curve:

- **Streaming answer** with a blinking cursor → the operator sees the
  model "thinking" instead of staring at a spinner.
- **Live tool-call cards** with a pulsing amber border while running,
  turning green with a result preview when done → the operator
  literally sees the model fetch sensors, then check faults, then
  predict, in real time.
- **Expandable tool trace** after the answer → for verification: every
  number in the answer can be traced back to the tool result it came
  from. This is critical for trust in an industrial setting.
- **Suggested prompts** on the empty state → guides new operators to the
  questions the system answers well.
- **Sidebar status pill** (online / offline) → operators know
  immediately if the backend is reachable.

---

## 9. Why the System Instruction Is Strict About Grounding

The orchestrator's system prompt explicitly tells the model:

> Every factual claim in your answer MUST come from a tool result or
> confident IBR knowledge. Never fabricate readings, codes, timestamps,
> thresholds, or trends.

And it replaces the rigid 5-section template with **intent-based answer
shapes**: definition questions get a short explanation, lookups get one
sentence, predictions cite `predict_trend`, history questions list what
`get_fault_history` actually returned. The 5-section format
(*Current Status → Diagnosis → Root Cause → Immediate Actions →
Prevention*) is reserved for genuine fault-diagnosis questions.

**Why:** in a plant context, a hallucinated "feedwater pressure is
18.5 MPa" is worse than "I do not have that reading right now". Strict
grounding turns the LLM into an interpreter of the tools rather than a
source of facts on its own.

---

## 10. File Map (for the supervisor)

| Path                                       | Role                                                         |
| ------------------------------------------ | ------------------------------------------------------------ |
| `publisher/`                               | MQTT simulators for boiler, turbine, chimney sensors & faults |
| `subscriber/`, `consumers/`                | MQTT → InfluxDB bridge                                       |
| `assistant/config.py`                      | Single source of truth for thresholds, ranges, fault catalog |
| `assistant/agent/orchestrator.py`          | ReAct loop (`run`, `run_stream`)                             |
| `assistant/agent/tool_schemas.py`          | Function-calling schemas exposed to Gemini                   |
| `assistant/agent/tools/realtime_tool.py`   | Live sensor reads + status labelling                         |
| `assistant/agent/tools/fault_history.py`   | Recent faults query                                          |
| `assistant/agent/tools/predict_trend.py`   | Linear projection to threshold                               |
| `api/chatbot_api.py`                       | FastAPI: `/chat`, `/chat/stream`, `/status`, `/health`, ws   |
| `streamlit_app.py`                         | Operator UI (chat + live status)                             |

---

## 11. Summary for the Supervisor

- **Why agentic, not plain RAG:** the truth is in live time-series data,
  not in a document store.
- **Why a fine-tuned model:** domain vocabulary, IBR framing, reliable
  tool selection.
- **Why ReAct:** multi-step diagnosis, transparent audit trail, bounded
  loop.
- **Why three tools:** each answers a distinct kind of question
  (*now*, *recent*, *future*) and offloads arithmetic from the LLM to
  deterministic Python.
- **Why SSE streaming + tool-call cards:** trust comes from seeing the
  model fetch real data, not from a polished paragraph.
- **Why a strict system prompt:** the cost of a hallucinated reading in
  a plant is much higher than the cost of saying "I do not know".
