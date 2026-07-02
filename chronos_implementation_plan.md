# Chronos Integration — Implementation Plan

**Target system:** Boiler-IOT-Simulation (Vertex AI Gemini ReAct agent + InfluxDB + MQTT + Chroma KB)
**Goal:** Add Chronos-T5 probabilistic forecasting as a sidecar — turn system from reactive (alarm) to predictive (forecast).
**Source guide:** `chronos_boiler_integration.md`

---

## 0. Current State (verified from repo)

| Component | File | Status |
|---|---|---|
| ReAct orchestrator | `assistant/agent/orchestrator.py` | exists, Vertex AI Gemini |
| Tool registry | `orchestrator.py:39` `TOOL_REGISTRY` | 4 tools registered |
| `fetch_realtime_sensors` | `assistant/agent/tools/realtime_tool.py` | keep as-is |
| `search_knowledge_base` | `assistant/agent/tools/knowledge_tool.py` | keep as-is |
| `get_fault_history` | `assistant/agent/tools/fault_history.py` | keep as-is |
| `predict_trend` | `assistant/agent/tools/predict_trend.py` | linear regression over InfluxDB — **replace internals** |
| Tool schemas | `assistant/agent/tool_schemas.py` | add 1 schema |
| Evaluator | `evaluation/evaluator.py` | extend for forecast metrics |
| Data store | InfluxDB (not in-memory deque) | source for Chronos history |
| API | `api/chatbot_api.py` | start background thread here |

**Deviation from guide:** Guide assumes raw MQTT in-process `SensorBuffer`. Repo already persists to InfluxDB. Use InfluxDB as history source — skip the `SensorBuffer` class. Saves work + matches existing arch.

---

## 1. Scope & Non-Goals

**In scope**
- New `chronos_service.py` (single file).
- Background refresh thread populating `chronos_cache` dict.
- Replace `predict_trend` internals (keep signature → string return).
- New tool `get_chronos_forecast`.
- Tool schema entry + orchestrator system prompt update.
- Evaluation: forecast accuracy (MAPE, sMAPE), lead-time-to-fault, anomaly precision/recall.

**Out of scope (per guide §10)**
- Separate Redis. Use in-process dict.
- REST wrapper around Chronos.
- Per-request inference. Refresh every 30s.
- Custom transformer from scratch.

---

## 2. Phased Plan

### Phase 1 — Setup (½ day)

1. `pip install chronos-forecasting torch pandas numpy` → add to `requirements.txt` + `pyproject.toml`.
2. Add env vars to `.env` + `assistant/config.py`:
   ```
   CHRONOS_MODEL=amazon/chronos-t5-small
   CHRONOS_DEVICE=cpu
   CHRONOS_REFRESH_INTERVAL=30
   CHRONOS_PREDICTION_LENGTH=20
   CHRONOS_STEP_INTERVAL=10
   CHRONOS_HISTORY_MINUTES=20
   ```
3. Smoke test: load `chronos-t5-small`, run 1 forecast on dummy data. Confirm <300ms CPU latency.

**Acceptance:** model loads, `forecast_sensor` returns `SensorForecast` for a 128-point synthetic series.

---

### Phase 2 — Chronos Service (1 day)

Create `assistant/agent/chronos_service.py` per guide §5.2 with adaptations:

- Replace `SensorBuffer` dependency with **InfluxDB history fetcher**:
  ```python
  def _fetch_history(sensor: str, minutes: int) -> list[float]:
      # Reuse InfluxDB client from predict_trend.py
      # Same Flux query, return values list
  ```
- `THRESHOLDS` dict: mirror `SENSOR_NORMAL_RANGE` from `assistant/config.py` (single source of truth — import, don't duplicate).
- Module-level singleton: `chronos_service = ChronosService(...)`, `chronos_cache: dict[str, SensorForecast] = {}`.
- `format_for_llm_context()` — unchanged from guide.

**Files touched**
- NEW: `assistant/agent/chronos_service.py`
- MODIFY: `assistant/config.py` (add Chronos config knobs)

**Acceptance:** `forecast_all_sensors()` returns dict of forecasts for all 11 sensors using InfluxDB data, <500ms.

---

### Phase 3 — Background Refresh Thread (½ day)

Wire startup in `api/chatbot_api.py`:

```python
import threading
from assistant.agent.chronos_service import chronos_service, chronos_cache, refresh_loop

@app.on_event("startup")
def start_chronos():
    t = threading.Thread(target=refresh_loop, daemon=True)
    t.start()
```

Add `refresh_loop()` inside `chronos_service.py` that:
- Sleeps `CHRONOS_REFRESH_INTERVAL` seconds.
- Pulls history from InfluxDB per sensor.
- Calls `forecast_all_sensors`.
- Updates `chronos_cache` atomically (dict swap).
- Logs failures, never crashes thread.

**Acceptance:** API boots, log shows `Chronos ready`, cache populated after first cycle, `/health` reports `sensors_forecasted: 11`.

---

### Phase 4 — Tool Integration (½ day)

#### 4a. Replace `predict_trend` internals
File: `assistant/agent/tools/predict_trend.py`

- Keep signature `predict_trend(sensor_name: str, window_minutes: int = 30) -> str`.
- Keep string return (orchestrator expects str via `execute_tool`).
- New flow:
  1. Look up `chronos_cache[sensor_name]`.
  2. If hit → format Chronos forecast (current val, projected val, rate, time-to-warn, time-to-critical, anomaly score, confidence band).
  3. If miss → fall back to existing linear regression (already implemented — keep as `_legacy_predict_trend`).
- Delete unused regression code path **only after Chronos validated in eval**.

#### 4b. New tool `get_chronos_forecast`
File: NEW `assistant/agent/tools/chronos_tool.py`

```python
def get_chronos_forecast(sensor_name: str = "all") -> str:
    """Return Chronos probabilistic forecast for one or all sensors."""
    # Read chronos_cache, format as string
```

Return string (consistent with other tools).

#### 4c. Register in orchestrator
File: `assistant/agent/orchestrator.py:39`

```python
from assistant.agent.tools.chronos_tool import get_chronos_forecast
TOOL_REGISTRY = {
    ...,
    "get_chronos_forecast": get_chronos_forecast,
}
```

#### 4d. Tool schema
File: `assistant/agent/tool_schemas.py` — append Gemini function schema for `get_chronos_forecast` with one optional `sensor_name` param.

#### 4e. System prompt
File: `assistant/agent/orchestrator.py:70` — extend tool inventory section to describe `get_chronos_forecast` as FUTURE/PROBABILISTIC intent (vs `predict_trend` for simpler trend Q's). Add to decision procedure (§7 below).

**Acceptance:** ReAct loop calls `get_chronos_forecast` on question "Will boiler overheat in 30 min?", agent answer cites `minutes_to_critical`.

---

### Phase 5 — Inject Chronos Context into System Prompt (¼ day)

In `BoilerAgentOrchestrator.__init__` or per-`run()`:

```python
chronos_block = chronos_service.format_for_llm_context(chronos_cache) if chronos_cache else ""
# Append to system_instruction OR prepend as first user turn
```

Decision: append per-`run()` as part of first user `Content` (not system prompt) — Vertex AI caches system_instruction, but forecast changes every 30s. Keep system prompt static.

**Acceptance:** When a sensor has projected critical breach, prompt contains the URGENT FORECAST block; LLM proactively mentions it.

---

### Phase 6 — Evaluation (1 day)

Extend `evaluation/evaluator.py` with forecast-specific metrics. Three buckets:

#### 6a. Forecast accuracy (numerical)
- Hold out last 20% of historical sensor data per sensor.
- Run Chronos on first 80%, compare predicted vs actual.
- Metrics:
  - **MAPE** (Mean Absolute Percentage Error) — per sensor.
  - **sMAPE** — symmetric, handles near-zero values (water_level).
  - **Quantile loss @ 10/50/90** — calibration of probabilistic forecast.
- Pass criterion: MAPE < 15% on temperature/pressure, < 25% on emissions.

#### 6b. Fault lead-time
- Replay logged fault events.
- For each fault, compute "minutes_to_critical" Chronos predicted before the actual breach.
- Metric: median lead time, % faults with ≥10 min lead time.
- Pass criterion: ≥70% faults predicted ≥10 min ahead, median ≥15 min.

#### 6c. Anomaly precision/recall
- Label historical windows: fault-adjacent (60 min before logged fault) = positive.
- Use Chronos `anomaly_score > 0.7` as detector.
- Compute precision, recall, F1.
- Pass criterion: F1 ≥ 0.6 zero-shot; ≥ 0.75 after fine-tune.

#### 6d. End-to-end RAGAS (existing)
- Add 20 forecast-style questions to eval set (e.g. "Will flue temp breach in next 30 min?", "Any sensor at risk?").
- Re-run RAGAS faithfulness/answer_relevancy with Chronos enabled vs disabled.
- Pass criterion: faithfulness +5pp, no regression on existing question categories.

**Deliverable:** `evaluation/chronos_eval.py` + report `evaluation/results/chronos_baseline.md`.

---

### Phase 7 — (Optional) Fine-Tuning (1 day, after Phase 6 baseline)

Only if Phase 6a MAPE > 15% OR Phase 6b lead-time < 10 min.

1. Export 25K InfluxDB readings → pandas → GluonTS format (guide §9.1).
2. Train per guide §9.2 on Colab T4 (~45 min).
3. Save to `models/chronos-boiler-finetuned/`.
4. Set `CHRONOS_MODEL=./models/chronos-boiler-finetuned`.
5. Re-run Phase 6 evaluation; commit only if metrics improve.

---

### Phase 8 — Deployment & Monitoring (½ day)

1. Health endpoint `/health/chronos` in `api/chatbot_api.py` per guide §12.
2. Log every refresh cycle: sensors processed, cache age, warning/critical counts.
3. Docker: bump memory limit to 2GB.
4. Alert if `chronos_cache` stale > 120s.

---

## 3. File-Change Summary

| File | Action | Lines |
|---|---|---|
| `assistant/agent/chronos_service.py` | NEW | ~250 |
| `assistant/agent/tools/chronos_tool.py` | NEW | ~40 |
| `assistant/agent/tools/predict_trend.py` | MODIFY internals | ~50 changed |
| `assistant/agent/orchestrator.py` | ADD 1 tool entry + prompt block + import | ~15 |
| `assistant/agent/tool_schemas.py` | ADD 1 schema | ~20 |
| `assistant/config.py` | ADD env knobs | ~10 |
| `api/chatbot_api.py` | startup thread + /health | ~25 |
| `evaluation/evaluator.py` | extend | ~30 |
| `evaluation/chronos_eval.py` | NEW | ~200 |
| `requirements.txt`, `pyproject.toml` | add deps | ~3 |
| `.env` | add Chronos vars | ~6 |
| `fetch_realtime_sensors`, `fault_history`, `knowledge_tool` | NO CHANGE | 0 |

---

## 4. Risk & Mitigations

| Risk | Mitigation |
|---|---|
| First load of `chronos-t5-small` downloads 180MB on cold boot → API startup slow | Pre-download in Docker image build step; cache mount. |
| `predict_trend` regression on questions where Chronos cache empty (boot window) | Fallback to legacy linear regression for ~60s after start. |
| Background thread silently dies → stale forecasts | Wrap loop in try/except, log error, watchdog timestamp in cache; `/health` checks age. |
| Chronos forecast disagrees with `detect_fault` → contradictory LLM answer | System prompt already has conflict-disclosure rule (`orchestrator.py:196`); update prompt to explicitly cover threshold-vs-forecast conflict. |
| Memory spike under load (Chronos 500MB + LLM) | Single global pipeline, no per-request load. Add memory_limit to compose. |
| Threshold direction (low-side breach for `water_level`, `o2_level`) handled wrong | Unit tests on `_check_breach` with rising and falling synthetic series. |

---

## 5. Acceptance Criteria (whole feature)

- [ ] `/health/chronos` returns `sensors_forecasted >= 11` within 60s of boot.
- [ ] Question "Will any sensor breach in next 30 min?" triggers `get_chronos_forecast`, answer cites `minutes_to_critical` from forecast.
- [ ] `predict_trend` returns Chronos-backed output when cache populated, legacy when not.
- [ ] Eval: MAPE thresholds met (Phase 6a), median lead time ≥15 min (Phase 6b), F1 ≥0.6 (Phase 6c).
- [ ] RAGAS faithfulness on new forecast questions ≥0.85.
- [ ] No regression on existing tool routing (run current eval suite, expect equal or better scores).
- [ ] Memory <2GB under steady load.

---

## 6. Estimated Effort

| Phase | Days |
|---|---|
| 1. Setup | 0.5 |
| 2. Service | 1.0 |
| 3. Background thread | 0.5 |
| 4. Tool integration | 0.5 |
| 5. Prompt context | 0.25 |
| 6. Evaluation | 1.0 |
| 7. Fine-tune (optional) | 1.0 |
| 8. Deployment | 0.5 |
| **Total (no fine-tune)** | **4.25 days** |
| **Total (with fine-tune)** | **5.25 days** |

---

## 7. Decision Procedure Addition (for system prompt §70)

Add to "Available tools" inventory:

```
- get_chronos_forecast → PROBABILISTIC FUTURE intent. The question asks about
  likelihood, confidence, anomaly, "will X happen", "how long until fault",
  "is anything about to fail", or multi-sensor risk scan. Returns probabilistic
  forecast with confidence bands, anomaly score, and minutes-to-warning/critical.
  Prefer this over predict_trend when the question implies uncertainty or risk
  ranking. Use predict_trend for simple "is X rising/falling" questions.
```

---

## 8. Open Questions (resolve before Phase 4)

1. Should `predict_trend` and `get_chronos_forecast` coexist or should `predict_trend` be deprecated once Chronos is stable? **Recommendation:** keep both during ramp; reassess after Phase 6 eval.
2. Persist forecasts to InfluxDB for audit trail? **Recommendation:** no for v1, in-memory only; revisit if compliance demands.
3. Per-sensor model vs single multi-series model? **Recommendation:** single pipeline, looped per sensor (guide §5.2) — Chronos handles univariate well, multivariate gain is marginal.
