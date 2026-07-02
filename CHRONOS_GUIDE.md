# Chronos in Boiler-IoT POC — Client Guide

> Probabilistic time-series forecasting layer for predictive fault detection.
> Use this guide to walk a non-technical client through what Chronos does, what
> works today, and what would be needed for a production rollout.

---

## 1. What Chronos Is (one-paragraph version)

Chronos is a **pre-trained foundation model for time-series forecasting**, released
by Amazon Science. We use the variant `amazon/chronos-t5-small` (~46M params,
T5-encoder architecture). Unlike a classical model (ARIMA, Prophet), Chronos
treats a stream of sensor readings the way a language model treats a stream of
tokens — it learns from millions of historical time-series and can forecast a
new sensor it has **never seen before**, with **zero retraining**.

For this POC, Chronos watches every boiler / chimney / turbine sensor live and
answers one question every 30 seconds:

> "Given the last 20 minutes of readings, what will this sensor look like for the
> next ~3.3 minutes, and how likely is it to cross a warning or critical threshold?"

---

## 2. Why It Matters For This Project

| Without Chronos | With Chronos |
|---|---|
| Alerts fire **after** a threshold is breached. | Alerts fire **before** a breach (lead time: ~1–5 min). |
| Operator sees current value only. | Operator sees current value **+ probable future trajectory with confidence band**. |
| Single point estimate — no uncertainty. | Median forecast + 10th / 90th percentile band. |
| Per-sensor logic must be hand-coded. | One model handles all 20+ sensors, zero per-sensor tuning. |
| Cannot detect "this reading is statistically weird even though it's in range". | Built-in **anomaly score** (0.0–1.0) flags unusual values. |

**Plain-language pitch for the client:**
> "Today the plant reacts. With Chronos, the plant predicts. We get a 1–5 minute
> head start before the boiler enters a danger zone, with a confidence interval
> the operator can trust."

---

## 3. How Chronos Predicts — End-to-End Flow

```
┌──────────────┐   MQTT    ┌──────────┐  every 30s   ┌──────────────┐
│  Simulator   │ ────────▶ │ InfluxDB │ ─────────▶   │ refresh_loop │
│ (boiler.py)  │  10s tick │ (bucket) │ history pull │   thread     │
└──────────────┘           └──────────┘              └──────┬───────┘
                                                            │
                                              20 min history per sensor
                                                            │
                                                            ▼
                                                  ┌──────────────────┐
                                                  │ ChronosPipeline  │
                                                  │ predict() — T5   │
                                                  │ 20 future steps  │
                                                  │ 20 MC samples    │
                                                  └────────┬─────────┘
                                                           │
                              median / 10p / 90p / anomaly score
                                                           │
                                                           ▼
                                                  ┌──────────────────┐
                                                  │  chronos_cache   │
                                                  │  (in-memory)     │
                                                  └────────┬─────────┘
                                                           │
                       ┌───────────────────────────────────┼───────────────┐
                       │                                   │               │
                       ▼                                   ▼               ▼
              ┌────────────────┐               ┌────────────────────┐  ┌──────────────┐
              │ alert_monitor  │               │ Agent tool         │  │  /chronos/   │
              │ loop (15s)     │               │ get_chronos_       │  │  forecast    │
              │ — auto-recover │               │ forecast(...)      │  │  REST API    │
              └────────────────┘               └────────────────────┘  └──────────────┘
```

### Step-by-step (code references)

1. **Sensor publish** — `publisher/simulators/boiler_simulator.py` emits readings
   every 0.5 s; broker pushes to InfluxDB measurement `boiler_sensors` /
   `chimney_sensors` / `turbine_sensors`.

2. **History fetch** — `assistant/agent/chronos_service.py:63`
   `_fetch_influx_history(sensor, minutes=20)` runs a Flux query and returns
   the float series ordered oldest→newest.

3. **Forecast** — `chronos_service.py:220` `forecast_sensor(...)`:
   * Wraps history into a 1×N `torch.float32` tensor.
   * Calls `ChronosPipeline.predict(context, prediction_length=20, num_samples=20)`.
   * Returns a `(20 samples × 20 steps)` matrix of plausible futures.
   * **Median** of samples → point forecast.
   * **10th percentile** → optimistic / pessimistic lower bound.
   * **90th percentile** → upper bound.

4. **Threshold scan (3-tier probabilistic)** — `forecast_sensor` evaluates
   breach in three stages and records the winning source in `breach_source`:
   * **Stage 1 — current value**: if today's reading already breaches
     critical → `minutes_to_critical = 0`, `breach_source = "current"`.
   * **Stage 2 — risk band**: scans `max(median, upper_bound)` (high-direction)
     or `min(median, lower_bound)` (low). 90th-percentile crossings count as
     real probabilistic risk, not just median crossings. `breach_source = "chronos"`.
   * **Stage 3 — slope override**: least-squares linear fit over last 30
     readings. If recent drift toward threshold is clear and Chronos's median
     is flat (under-reaction to monotonic ramps), the projected breach time
     wins. `breach_source = "slope"`.
   * Thresholds pulled from `SENSOR_NORMAL_RANGE` (warn) and
     `SENSOR_CRITICAL_RANGE` (crit) in `assistant/config.py`.

5. **Anomaly score** — `_compute_anomaly_score` (line 331). Measures how far
   the most-recent actual reading deviates from the Chronos-expected
   distribution at T+1, normalised by the 10–90 band width. `1.0` = statistically
   extreme, `0.0` = perfectly expected.

6. **Cache update** — atomic write under `_cache_lock` (line 468). Stale sensors
   that didn't refresh are evicted to prevent dashboards showing zombie
   forecasts.

7. **Consumers:**
   * Alert manager → fault generation + auto-recovery.
   * LLM agent tool → answer predictive user questions.
   * REST `/chronos/forecast` endpoint → dashboard chart.

### Tuning knobs (env vars, in `assistant/config.py:229`)

| Var | Default | Meaning |
|---|---|---|
| `CHRONOS_MODEL` | `amazon/chronos-t5-small` | HuggingFace model id. Swap for `-base` (200M) or `-large` (710M) if GPU available. |
| `CHRONOS_DEVICE` | `cpu` | Set `cuda` if GPU present. |
| `CHRONOS_REFRESH_INTERVAL` | `30` s | Background loop cadence. |
| `CHRONOS_PREDICTION_LENGTH` | `20` steps | Forecast horizon (20 steps × 10s = 200s ≈ 3.3 min). |
| `CHRONOS_STEP_INTERVAL` | `10` s | Seconds per step. |
| `CHRONOS_HISTORY_MINUTES` | `20` | History window pulled from InfluxDB per refresh. |

---

## 4. Capabilities — Quick Catalogue

| # | Capability | Source of truth |
|---|---|---|
| 1 | Point forecast (median) per sensor | `SensorForecast.forecast_values` |
| 2 | Probabilistic confidence band (10p/90p) | `lower_bound` / `upper_bound` |
| 3 | Minutes to **warning** threshold | `minutes_to_warning` |
| 4 | Minutes to **critical** threshold | `minutes_to_critical` |
| 5 | Anomaly score per sensor | `anomaly_score` |
| 5a | Linear-slope projection (ramp fallback) | `slope_per_step` + `breach_source = "slope"` |
| 5b | Probabilistic breach detection (uses 90p band, not just median) | `breach_source = "chronos"` |
| 5c | Current-value immediate breach (ttc=0 if already over) | `breach_source = "current"` |
| 6 | Multi-sensor batch forecast every 30s | `refresh_loop` |
| 7 | Per-sensor 120s alert cooldown (no thrash) | `alert_manager.py:204` |
| 8 | Direction-aware thresholds (e.g. low O₂ is dangerous) | `_build_threshold_map` |
| 9 | LLM-callable predictive tool | `get_chronos_forecast` |
| 10 | Dashboard REST forecast | `/chronos/forecast` |
| 11 | Real-time alert WebSocket | `/ws/alerts` |
| 12 | Auto-recovery flip (degradation → normal) | `_trigger_auto_recovery` |

---

## 5. What Works Today (POC Scope)

### ✅ Working — confirmed in code

| Feature | Where | Behaviour |
|---|---|---|
| **Cold-start zero-training forecasting** | `chronos_service.ChronosService.__init__` | Loads pretrained T5 once at boot, ~5–10 s on CPU. |
| **Background refresh every 30 s** | `refresh_loop` | Daemon thread; survives single-sensor errors. |
| **20-step / 3.3-min horizon** | `CHRONOS_PREDICTION_LENGTH` × `CHRONOS_STEP_INTERVAL` | Configurable. |
| **Confidence band from 20 Monte Carlo samples** | `forecast_sensor` | Returns full sample matrix → median + percentiles. |
| **Threshold breach detection** | `forecast_sensor:262` | Direction-aware (high vs low). |
| **Anomaly scoring** | `_compute_anomaly_score` | Relative to Chronos-expected distribution. |
| **Auto-recovery in degradation mode** | `alert_manager.alert_monitor_loop` | Detects `minutes_to_critical ≤ 5` → writes fault → broadcasts WS → resets sim mode → simulator snaps back. |
| **Two-tier alerts** | `alert_manager.py:251` | WARNING tier (≤ 5 min) + CRITICAL tier (≤ 5 min); critical owns sensor when both fire. |
| **Per-sensor cooldown** | `_ALERT_COOLDOWN_SECONDS = 120` | Same sensor cannot re-fire within 2 min. |
| **Influx-backed history** | `_fetch_influx_history` | Single source of truth — no in-process buffer drift. |
| **Stale forecast eviction** | `refresh_loop:470` | Cache only contains *currently refreshed* sensors. |
| **LLM tool integration** | `chronos_tool.get_chronos_forecast` | Returns rich formatted string the agent can cite. |
| **System-prompt injection** | `chronos_service.format_for_llm_context` | Urgent forecasts prepended to every user turn so agent always knows risk state. |
| **REST endpoint** | `GET /chronos/forecast[?sensor=...]` | Returns single or all sensors sorted by urgency. |
| **Health endpoint** | `GET /health/chronos` | Returns `healthy`/`warming_up`/`stale` based on cache age. |
| **Dashboard chart** | `Frontend/components/ChronosForecastChart.tsx` | Plots history + median + confidence band. |
| **WebSocket live alerts** | `/ws/alerts` + `AlertBanner.tsx` | Banner appears in dashboard when CRITICAL forecast hits. |
| **Root-cause hints in alerts** | `alert_manager._ROOT_CAUSE` | Each sensor maps to plain-English likely cause. |
| **Affected-sensor enrichment** | `_build_affected_sensors` | Alert payload lists every sensor in same severity tier. |

### Working but limited

| Feature | Limit / Caveat |
|---|---|
| Degradation simulation | Only `main_steam_temp_boiler` ramps + `feedwater_temp` drops. Other sensors stay idle in degradation mode. |
| Auto-recovery | Snaps simulator back to mean immediately (line 300 of `boiler_simulator.py`) — not a gradual cooldown. |
| Anomaly score | Compares against Chronos's *predicted* distribution, not against historical baseline — can be noisy on new sensors. |
| Forecast horizon | 3.3 min by default. Useful for imminent breaches; not for hours-ahead planning. |
| Model size | `chronos-t5-small` (46M) — fastest CPU option but lowest accuracy on monotonic ramps. Mitigated by slope override. |
| Refresh cadence | 30 s. Sub-second urgent breaches will be missed. |
| Cooldown | Sensor-level only — multiple sensors can fire in quick succession without rate-limit. |
| Threshold direction list | Hard-coded set `LOW_SIDE_SENSORS = {oxygen_level, o2, condenser_vacuum, draft}` — adding a new low-side sensor needs code edit. |
| Slope override | Linear extrapolation only; doesn't model acceleration or saturation. Window = last 30 readings (5 min) — short-burst spikes get under-weighted. |

---

## 6. NOT Implemented Yet — Needed for Production

Frame these to the client as **POC → Pilot → Production** roadmap items.

### Tier 1 — Production blockers

| Gap | Why it matters | What's needed |
|---|---|---|
| **Fine-tuning on plant-specific data** | Pretrained Chronos is generic — accuracy on this exact boiler can improve 20–40 % with domain fine-tuning. | Collect 1–2 months of real plant history; run `evaluation/finetune_chronos.py` (file exists but not productionised); A/B test new vs base model. |
| **GPU inference** | CPU forecast takes ~200–800 ms per sensor × 20 sensors = serial 4–16 s. Won't scale. | Deploy on T4/L4 GPU; expect 10–30× speedup; batch all sensors in single forward pass. |
| **Forecast accuracy monitoring** | No feedback loop — we never measure how often Chronos was *right*. | Log forecasted vs actual into a `chronos_predictions` Influx measurement; backfill MAPE / coverage every hour; surface in Grafana. |
| **Persisted alert history** | Alerts written to `fault_events` but no dedicated `chronos_alerts` measurement → hard to audit. | Add `chronos_alerts` measurement, retain 90 days, expose Grafana panel. |
| **Multi-instance safety** | `chronos_cache` is in-process. Two FastAPI replicas → two diverging caches. | Move cache to Redis (already running) or use sticky session per replica. |

### Tier 2 — High value adds

| Gap | What it gives | Implementation sketch |
|---|---|---|
| **Multivariate forecasting** | Treat correlated sensors jointly — e.g. CO ↑ + O₂ ↓ → combustion fault. | Chronos-Bolt supports covariates; restructure history fetch into `(sensor, value, ts)` tuples. |
| **Long-horizon forecast (30–60 min)** | Maintenance scheduling, load planning. | Either run a second pipeline at `prediction_length=180`, or use Chronos-Bolt with patch tokens. |
| **Adaptive thresholds** | Static warn/crit bands don't reflect load conditions. | Compute rolling 7-day percentile per sensor per load tier; replace static `SENSOR_NORMAL_RANGE`. |
| **Forecast explanation** | Operator wants *why* Chronos predicts breach. | SHAP-style attribution per input timestep; OR cross-reference with anomaly score + recent slope. |
| **Root-cause correlation engine** | One CRITICAL alert often triggers cascading WARN alerts. Currently each is separate. | Cluster simultaneous alerts; surface "primary cause" sensor. |
| **Backtest harness** | Prove ROI to plant manager. | Replay 30 days of history into Chronos, count how many real faults it caught N minutes early. |
| **Drift detection** | Plant aging shifts baselines; Chronos accuracy decays silently. | Track week-over-week forecast error; alert if MAPE doubles. |
| **Sensor-failure detection** | Flat-lined / stuck sensor today gets a "great forecast" — model loves constants. | Add data-quality pre-check: variance, NaN%, last-update-age. Drop sensors from forecasting if degraded. |

### Tier 3 — Nice to have

| Gap | Description |
|---|---|
| Per-sensor model selection | Some sensors benefit from `-base`, others fine with `-small`. Per-sensor config. |
| User-configurable horizons | Let operator ask "forecast 1 hr" via UI slider. |
| Confidence-aware alerting | Only fire alert if 90p band also crosses critical, not just median. |
| Mobile push notifications | Forward `/ws/alerts` events to FCM / APNS. |
| Forecast diffing | "Show how today's forecast compares to yesterday's at this hour." |
| n8n workflow trigger | On critical alert, run automated remediation playbook. |

### Known bugs / TODO in current code

* `_broadcast_alert_sync` creates a fresh `asyncio` loop per WebSocket per
  alert (`alert_manager.py:188`) — works for POC but wasteful. Should use a
  single shared loop or `asgiref.sync.async_to_sync`.
* `forecast_sensor` raises `ValueError` if history <10 readings; refresh_loop
  catches it, but on a freshly-bootstrapped sensor the LLM tool may still
  receive `cache warming up`. Add a "minimum-confidence" return path.
* Anomaly score uses `samples[:, 0]` (only T+1 step) — under-uses available
  signal. Could integrate across full horizon.
* No retry / circuit-breaker on InfluxDB query failure — silently empty
  forecast for the cycle.

---

## 7. How To Demo It Live

```bash
# 1. Bring up infra
docker compose up -d

# 2. Start simulator + API
python -m publisher.simulators.boiler_simulator &
uvicorn api.chatbot_api:app --port 8000

# 3. Wait ~30 s for first refresh, then check health
curl http://localhost:8000/health/chronos
# expect: {"status":"healthy","sensors_forecasted":N,...}

# 4. Inspect raw forecast
curl http://localhost:8000/chronos/forecast | jq

# 5. Trigger degradation → auto-recovery
curl -X POST http://localhost:8000/simulation/mode \
     -H "Content-Type: application/json" \
     -d '{"mode":"degradation"}'

# 6. Watch FastAPI console — within 60–90 s you should see:
#    🚨 CHRONOS CRITICAL: sensor=main_steam_temp_boiler | ttc=X min
#    🔄 AUTO-RECOVERY activated — Simulation mode → NORMAL.

# 7. Ask the agent a predictive question
curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"question":"Will any sensor breach critical in the next 5 minutes?"}'
```

In the dashboard:
* `ChronosForecastChart` shows history + forecast + confidence band.
* `AlertBanner` pops on CRITICAL via `/ws/alerts`.
* `SimulationModeToggle` lets client trigger the demo themselves.

---

## 8. One-Slide Client Summary

> **What:** Chronos = Amazon's pretrained time-series transformer.
> **Where:** Background service in our agentic-RAG stack.
> **What it does:** Every 30 s, forecasts the next 3 minutes of every sensor
> with confidence bands and an anomaly score.
> **POC delivers:** Predictive alerts 1–5 min before breach, auto-recovery
> demo, LLM agent that cites forecasts, live dashboard chart, REST + WebSocket
> APIs.
> **Pilot needs:** Fine-tuning on real plant data, GPU inference, accuracy
> monitoring, persisted alert history.
> **Production needs:** Multivariate forecasting, adaptive thresholds,
> backtest report, drift detection.

---

## 9. File Map (for engineering hand-off)

| Concern | File |
|---|---|
| Model load + forecast logic | `assistant/agent/chronos_service.py` |
| Threshold tuning | `assistant/config.py` (`SENSOR_NORMAL_RANGE`, `SENSOR_CRITICAL_RANGE`) |
| Auto-recovery + alerts | `assistant/agent/alert_manager.py` |
| LLM agent tool | `assistant/agent/tools/chronos_tool.py` |
| REST + WebSocket APIs | `api/chatbot_api.py` |
| Frontend chart | `Frontend/components/ChronosForecastChart.tsx` |
| Frontend banner | `Frontend/components/AlertBanner.tsx` |
| Simulator degradation hook | `publisher/simulators/boiler_simulator.py` |
| Fine-tune scaffold | `evaluation/finetune_chronos.py` |
| Eval scaffold | `evaluation/chronos_eval.py` |
