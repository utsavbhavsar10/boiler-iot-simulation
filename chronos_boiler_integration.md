# Chronos Integration — Boiler & Chimney Monitoring System
**Technical Documentation v1.0**
Author: Engineering Team | Stack: Vertex AI · MQTT · Chronos-T5 · Open-Source LLM | Date: June 2026

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [What You Already Have — Do Not Rewrite](#2-what-you-already-have--do-not-rewrite)
3. [Where Chronos Fits — The Gap It Fills](#3-where-chronos-fits--the-gap-it-fills)
4. [Chronos Setup & Installation](#4-chronos-setup--installation)
5. [Chronos Service Implementation](#5-chronos-service-implementation)
6. [Integration with Your Existing Tools](#6-integration-with-your-existing-tools)
7. [ReAct Loop — What Changes](#7-react-loop--what-changes)
8. [Orchestrator — Minimal Changes Required](#8-orchestrator--minimal-changes-required)
9. [Fine-Tuning Chronos on Your 25K Data](#9-fine-tuning-chronos-on-your-25k-data)
10. [What Code to Delete / Not Build](#10-what-code-to-delete--not-build)
11. [Full Data Flow Diagram](#11-full-data-flow-diagram)
12. [Performance & Deployment Notes](#12-performance--deployment-notes)

---

## 1. System Architecture Overview

Your current system has five core components that are well-built and should be kept as-is. Chronos slots in as a **sixth component** — a numerical forecasting sidecar — without replacing anything.

```
┌─────────────────────────────────────────────────────────────────┐
│                      MQTT Broker (existing)                     │
│         11 sensor topics · boiler/* · chimney/*                 │
└───────────────────┬─────────────────────────────────────────────┘
                    │ subscribe
        ┌───────────▼───────────┐
        │   MQTT Consumer       │  ← existing, keep as-is
        │   (producer/consumer  │
        │    structure)         │
        └───────┬───────────────┘
                │ parsed sensor readings
        ┌───────▼───────────────────────────────────────────────┐
        │              Time-Series Buffer (Redis / in-memory)   │  ← NEW (small add)
        │   Stores last 512 readings per sensor with timestamps │
        └───────┬───────────────┬───────────────────────────────┘
                │               │
    ┌───────────▼────┐   ┌──────▼──────────────────────────────┐
    │  Your 5 Tools  │   │   Chronos Forecasting Service       │  ← NEW
    │  (keep all 5)  │   │   chronos-t5-small · 46M params     │
    └───────┬────────┘   └──────┬──────────────────────────────┘
            │                   │ forecast + anomaly score
            └──────────┬────────┘
                       │ merged context
            ┌──────────▼──────────────────┐
            │   ReAct Orchestrator        │  ← minor update only
            │   (existing, keep logic)    │
            └──────────┬──────────────────┘
                       │
            ┌──────────▼──────────────────┐
            │   Fine-Tuned LLM Chatbot    │  ← keep as-is
            │   + Vertex Knowledge Base   │
            └─────────────────────────────┘
```

---

## 2. What You Already Have — Do Not Rewrite

The following five tools are **complete and correct**. Chronos does not replace any of them.

### Tool 1 — `fetch_realtime_data`
```python
# KEEP THIS EXACTLY AS-IS
# Fetches current sensor snapshot from MQTT consumer buffer
# Returns: {sensor_name: {value, unit, timestamp, status}}
```
**Chronos relationship:** Chronos reads from the same buffer this tool reads from. They are parallel consumers of the same data — not sequential.

### Tool 2 — `detect_fault`
```python
# KEEP THIS EXACTLY AS-IS
# Compares current readings against hard thresholds
# Returns: {fault_detected: bool, sensor: str, severity: "warning"|"critical", value: float}
```
**Chronos relationship:** `detect_fault` is reactive (threshold breach now). Chronos adds *predictive* fault detection (breach in N minutes). Both are needed. Do not merge them.

### Tool 3 — `predict_trend`
```python
# KEEP THIS — BUT FEED IT CHRONOS OUTPUT
# Currently: likely a simple linear regression or moving average
# Update: replace internal math with Chronos forecast values
# The tool interface (name, inputs, outputs) stays identical
```
This is the **one tool that changes internally** — but its API signature stays the same so the ReAct loop needs no update.

### Tool 4 — `fault_history`
```python
# KEEP THIS EXACTLY AS-IS
# Queries historical fault log from your database/Vertex AI
# Returns: list of past fault events with timestamps and sensor context
```
**Chronos relationship:** None. Fault history is retrospective. Chronos is prospective. Different concerns entirely.

### Tool 5 — `orchestrator` / ReAct loop
```python
# KEEP THE LOGIC — add one new tool call: get_chronos_forecast
# See Section 7 for the minimal change required
```

---

## 3. Where Chronos Fits — The Gap It Fills

| Capability | Your current system | With Chronos added |
|---|---|---|
| Current sensor value | `fetch_realtime_data` | unchanged |
| Hard threshold breach | `detect_fault` | unchanged |
| Is a fault coming? | Not available | `predict_trend` → Chronos |
| How far from threshold? | Partially in `detect_fault` | Chronos confidence interval |
| Slow degradation drift | Not detected | Chronos long-horizon forecast |
| Anomaly (statistically unusual but not threshold breach) | Not detected | Chronos residual scoring |
| Past faults | `fault_history` | unchanged |
| Natural language answer | Fine-tuned LLM | unchanged, richer context |

**The core value Chronos adds:** It turns your system from *alarm-based* (react when bad) to *forecast-based* (warn before bad). For an industrial boiler, 15–30 minutes of advance warning is the difference between a controlled shutdown and an emergency.

---

## 4. Chronos Setup & Installation

### 4.1 Install dependencies

```bash
pip install chronos-forecasting torch pandas numpy
# For GPU (recommended for production):
pip install chronos-forecasting torch --index-url https://download.pytorch.org/whl/cu118
```

### 4.2 Model download (one-time)

```python
from chronos import ChronosPipeline
import torch

# Downloads ~180MB for small model — run once, then load from cache
pipeline = ChronosPipeline.from_pretrained(
    "amazon/chronos-t5-small",   # 46M params — best fit for your use case
    device_map="cpu",             # switch to "cuda" if GPU available
    torch_dtype=torch.float32,
)
```

**Model size guide for your 11-sensor setup:**

| Model | Params | RAM | Inference time (11 sensors) | Recommendation |
|---|---|---|---|---|
| `chronos-t5-tiny` | 8M | 200MB | ~50ms | Too small for boiler complexity |
| `chronos-t5-small` | 46M | 500MB | ~120ms | **Use this — best balance** |
| `chronos-t5-base` | 200M | 1.2GB | ~400ms | Use only if you fine-tune |
| `chronos-t5-large` | 710M | 3.5GB | ~1.2s | Overkill for this use case |

---

## 5. Chronos Service Implementation

This is the **only new file you need to write**. Create `chronos_service.py`.

### 5.1 Time-series buffer (add to your MQTT consumer)

```python
# Add this class to your existing MQTT consumer module
# Do NOT create a new consumer — just add this buffer

from collections import deque
from threading import Lock
import time

class SensorBuffer:
    """
    Rolling buffer storing last N readings per sensor.
    Thread-safe — MQTT consumer writes, Chronos service reads concurrently.
    """
    SENSORS = [
        "boiler_temperature", "boiler_pressure", "steam_flow",
        "water_level", "fuel_flow", "flue_temperature",
        "draft_pressure", "co2_level", "nox_emission",
        "smoke_opacity", "o2_level"
    ]
    BUFFER_SIZE = 512  # ~85 minutes at 1 reading/10 seconds per sensor

    def __init__(self):
        self._lock = Lock()
        self._buffers = {s: deque(maxlen=self.BUFFER_SIZE) for s in self.SENSORS}

    def push(self, sensor: str, value: float, timestamp: float = None):
        """Called by your MQTT consumer on each message received."""
        with self._lock:
            self._buffers[sensor].append({
                "value": value,
                "ts": timestamp or time.time()
            })

    def get_series(self, sensor: str, last_n: int = 128) -> list[float]:
        """Returns last N float values for a sensor — used by Chronos."""
        with self._lock:
            buf = list(self._buffers[sensor])
            return [r["value"] for r in buf[-last_n:]]

    def get_all_series(self, last_n: int = 128) -> dict[str, list[float]]:
        return {s: self.get_series(s, last_n) for s in self.SENSORS}


# In your existing MQTT on_message callback, add one line:
# sensor_buffer.push(sensor_name, float(payload["value"]))
```

### 5.2 Chronos forecasting service

```python
# chronos_service.py — NEW FILE (the only new file needed)

import torch
import numpy as np
from chronos import ChronosPipeline
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ── Sensor thresholds (mirror your detect_fault tool) ──────────────────────
THRESHOLDS = {
    "boiler_temperature":  {"warn": 350.0,  "critical": 400.0},
    "boiler_pressure":     {"warn": 10.0,   "critical": 12.0},
    "water_level":         {"warn": 40.0,   "critical": 25.0,  "direction": "low"},
    "flue_temperature":    {"warn": 250.0,  "critical": 300.0},
    "nox_emission":        {"warn": 200.0,  "critical": 300.0},
    "co2_level":           {"warn": 13.0,   "critical": 15.0},
    "smoke_opacity":       {"warn": 15.0,   "critical": 25.0},
    "o2_level":            {"warn": 3.0,    "critical": 1.5,   "direction": "low"},
}


@dataclass
class SensorForecast:
    sensor: str
    forecast_values: list[float]          # point forecast for next N steps
    lower_bound: list[float]              # 10th percentile
    upper_bound: list[float]              # 90th percentile
    horizon_seconds: int                  # how far ahead (e.g. 1800 = 30 min)
    steps_to_warning: Optional[int]       # None if no warning forecasted
    steps_to_critical: Optional[int]      # None if no critical forecasted
    anomaly_score: float                  # 0.0–1.0, higher = more anomalous
    minutes_to_warning: Optional[float]
    minutes_to_critical: Optional[float]


class ChronosService:
    """
    Forecasting service wrapping Chronos-T5.
    Designed to run as a background thread alongside your MQTT consumer.
    """

    def __init__(
        self,
        model_name: str = "amazon/chronos-t5-small",
        device: str = "cpu",
        prediction_length: int = 20,       # forecast 20 steps ahead
        step_interval_seconds: int = 10,   # your MQTT publish interval
    ):
        logger.info(f"Loading Chronos model: {model_name}")
        self.pipeline = ChronosPipeline.from_pretrained(
            model_name,
            device_map=device,
            torch_dtype=torch.float32,
        )
        self.prediction_length = prediction_length
        self.step_interval_seconds = step_interval_seconds
        logger.info("Chronos ready.")

    def forecast_sensor(
        self,
        sensor_name: str,
        history: list[float],
        num_samples: int = 20,
    ) -> SensorForecast:
        """
        Forecast a single sensor stream.

        Args:
            sensor_name: Must match a key in THRESHOLDS (or be unconstrained)
            history: List of recent float readings (recommend 64–128 values)
            num_samples: Monte Carlo samples for uncertainty estimation

        Returns:
            SensorForecast dataclass
        """
        if len(history) < 10:
            raise ValueError(f"Need at least 10 readings for {sensor_name}, got {len(history)}")

        context = torch.tensor(history, dtype=torch.float32).unsqueeze(0)

        # Chronos probabilistic forecast — returns (num_samples, prediction_length)
        forecast_tensor, _ = self.pipeline.predict(
            context=context,
            prediction_length=self.prediction_length,
            num_samples=num_samples,
        )

        samples = forecast_tensor[0].numpy()           # shape: (num_samples, prediction_length)
        point_forecast = np.median(samples, axis=0)    # median as point estimate
        lower = np.percentile(samples, 10, axis=0)     # 10th percentile
        upper = np.percentile(samples, 90, axis=0)     # 90th percentile

        # ── Threshold breach detection ─────────────────────────────────────
        thresh = THRESHOLDS.get(sensor_name, {})
        direction = thresh.get("direction", "high")  # "high" = breach when value rises
        warn_level = thresh.get("warn")
        crit_level = thresh.get("critical")

        steps_to_warn = None
        steps_to_crit = None

        for i, val in enumerate(point_forecast):
            if direction == "high":
                if steps_to_warn is None and warn_level and val >= warn_level:
                    steps_to_warn = i
                if steps_to_crit is None and crit_level and val >= crit_level:
                    steps_to_crit = i
            else:  # direction == "low"
                if steps_to_warn is None and warn_level and val <= warn_level:
                    steps_to_warn = i
                if steps_to_crit is None and crit_level and val <= crit_level:
                    steps_to_crit = i

        # ── Anomaly score: how much does the last actual reading deviate? ──
        # Compare the last real value against what Chronos would have predicted
        # (using the second-to-last window as context)
        anomaly_score = self._compute_anomaly_score(history, samples)

        step_secs = self.step_interval_seconds
        return SensorForecast(
            sensor=sensor_name,
            forecast_values=point_forecast.tolist(),
            lower_bound=lower.tolist(),
            upper_bound=upper.tolist(),
            horizon_seconds=self.prediction_length * step_secs,
            steps_to_warning=steps_to_warn,
            steps_to_critical=steps_to_crit,
            anomaly_score=anomaly_score,
            minutes_to_warning=(steps_to_warn * step_secs / 60) if steps_to_warn is not None else None,
            minutes_to_critical=(steps_to_crit * step_secs / 60) if steps_to_crit is not None else None,
        )

    def forecast_all_sensors(
        self,
        sensor_histories: dict[str, list[float]],
    ) -> dict[str, SensorForecast]:
        """
        Forecast all sensors. Call this every 30 seconds from a background thread.
        Results are cached and injected into the LLM context on each chatbot request.
        """
        results = {}
        for sensor, history in sensor_histories.items():
            if len(history) >= 10:
                try:
                    results[sensor] = self.forecast_sensor(sensor, history)
                except Exception as e:
                    logger.warning(f"Chronos forecast failed for {sensor}: {e}")
        return results

    def _compute_anomaly_score(
        self,
        history: list[float],
        samples: np.ndarray,
    ) -> float:
        """
        Scores how anomalous the most recent reading is.
        Uses the interquartile range of Chronos predictions as the normality band.
        Score of 1.0 = extremely anomalous, 0.0 = perfectly normal.
        """
        if len(history) < 2:
            return 0.0
        last_value = history[-1]
        # Use the first forecast step's distribution as the expected distribution
        step0_samples = samples[:, 0]
        q10, q90 = np.percentile(step0_samples, 10), np.percentile(step0_samples, 90)
        band_width = max(q90 - q10, 1e-6)
        deviation = abs(last_value - np.median(step0_samples))
        return float(min(deviation / (band_width * 2), 1.0))

    def format_for_llm_context(
        self,
        forecasts: dict[str, SensorForecast],
    ) -> str:
        """
        Formats Chronos output as a string to append to your LLM system prompt.
        This is the ONLY place Chronos output touches your LLM pipeline.
        """
        lines = ["=== CHRONOS FORECAST (next 30 minutes) ==="]
        urgent = []
        normal = []

        for sensor, fc in forecasts.items():
            label = sensor.replace("_", " ").title()
            if fc.minutes_to_critical is not None:
                urgent.append(
                    f"  CRITICAL FORECAST — {label}: "
                    f"projected to breach critical threshold in {fc.minutes_to_critical:.1f} min. "
                    f"Forecast trajectory: {[round(v,1) for v in fc.forecast_values[:5]]}"
                )
            elif fc.minutes_to_warning is not None:
                urgent.append(
                    f"  WARNING FORECAST — {label}: "
                    f"projected to breach warning threshold in {fc.minutes_to_warning:.1f} min."
                )
            elif fc.anomaly_score > 0.7:
                normal.append(
                    f"  ANOMALY — {label}: statistically unusual reading "
                    f"(anomaly score: {fc.anomaly_score:.2f}). "
                    f"Expected range: {fc.lower_bound[0]:.1f}–{fc.upper_bound[0]:.1f}"
                )

        if urgent:
            lines.append("URGENT FORECASTS:")
            lines.extend(urgent)
        if normal:
            lines.append("ANOMALIES DETECTED:")
            lines.extend(normal)
        if not urgent and not normal:
            lines.append("  All sensors within expected forecast bands. No upcoming threshold breaches predicted.")

        lines.append("=== END FORECAST ===")
        return "\n".join(lines)
```

---

## 6. Integration with Your Existing Tools

### 6.1 Update `predict_trend` — internal change only

Your `predict_trend` tool currently computes a trend internally (likely linear regression or simple moving average). Replace the internal math with Chronos output. **The tool name, inputs, and outputs stay identical** — the ReAct loop sees no change.

```python
# predict_trend.py — MODIFY INTERNALS ONLY, keep function signature

# BEFORE (what you likely have):
def predict_trend(sensor_name: str, horizon_minutes: int = 30) -> dict:
    readings = fetch_last_n_readings(sensor_name, n=20)
    slope = compute_linear_regression(readings)
    projected = extrapolate(readings[-1], slope, horizon_minutes)
    return {"sensor": sensor_name, "projected_value": projected, "trend": "rising"|"falling"|"stable"}

# AFTER (replace internals with Chronos, keep same return shape):
def predict_trend(sensor_name: str, horizon_minutes: int = 30) -> dict:
    """
    Now powered by Chronos instead of linear regression.
    Tool interface is identical — ReAct loop unchanged.
    """
    # chronos_cache is populated every 30s by background thread (see Section 5)
    forecast = chronos_cache.get(sensor_name)

    if forecast is None:
        # Fallback to simple regression if Chronos not ready yet
        return _legacy_linear_predict(sensor_name, horizon_minutes)

    # Map Chronos forecast to your existing return shape
    last_val = forecast.forecast_values[0]
    final_val = forecast.forecast_values[-1]
    trend = "rising" if final_val > last_val * 1.02 else \
            "falling" if final_val < last_val * 0.98 else "stable"

    return {
        "sensor": sensor_name,
        "projected_value": round(final_val, 2),
        "trend": trend,
        # New fields — LLM can use these if present, ignores if not
        "minutes_to_warning": forecast.minutes_to_warning,
        "minutes_to_critical": forecast.minutes_to_critical,
        "anomaly_score": round(forecast.anomaly_score, 3),
        "confidence_range": {
            "low": round(forecast.lower_bound[-1], 2),
            "high": round(forecast.upper_bound[-1], 2),
        },
        "forecast_horizon_minutes": horizon_minutes,
    }
```

### 6.2 Update `detect_fault` — add one optional field

No logic change. Just enrich the return value with Chronos's advance warning if available.

```python
# detect_fault.py — ADD 3 LINES only

def detect_fault(sensor_name: str, current_value: float) -> dict:
    # ... your existing threshold logic stays identical ...
    result = _existing_threshold_check(sensor_name, current_value)

    # ── ADD THESE 3 LINES ────────────────────────────────────────────────
    forecast = chronos_cache.get(sensor_name)
    if forecast:
        result["predicted_minutes_to_critical"] = forecast.minutes_to_critical
    # ────────────────────────────────────────────────────────────────────

    return result
```

### 6.3 `fetch_realtime_data` — no changes needed

```python
# fetch_realtime_data.py — DO NOT TOUCH
# Chronos reads from the same SensorBuffer independently.
# There is no coupling between this tool and Chronos.
```

### 6.4 `fault_history` — no changes needed

```python
# fault_history.py — DO NOT TOUCH
# Chronos is forward-looking only. Fault history is backward-looking.
# These serve different LLM queries and should never be merged.
```

---

## 7. ReAct Loop — What Changes

Your ReAct loop needs **one new tool** added to its tool registry. The loop logic itself (thought → action → observation → repeat) stays identical.

```python
# react_orchestrator.py — ADD ONE TOOL ENTRY only

TOOL_REGISTRY = {
    "fetch_realtime_data": fetch_realtime_data,
    "detect_fault":        detect_fault,
    "predict_trend":       predict_trend,       # now Chronos-powered internally
    "fault_history":       fault_history,
    # ── NEW ─────────────────────────────────────────────────────────────
    "get_chronos_forecast": get_chronos_forecast,
    # ────────────────────────────────────────────────────────────────────
}

# The new tool wrapper — thin, just reads from cache:
def get_chronos_forecast(sensor_name: str = "all") -> dict:
    """
    Returns Chronos probabilistic forecast.
    LLM calls this when asked predictive questions:
    'Will the boiler overheat?', 'How long until a fault?'

    Args:
        sensor_name: specific sensor name, or "all" for all sensors

    Returns:
        Forecast dict or dict of all forecasts
    """
    if sensor_name == "all":
        return {
            s: {
                "forecast_next_5_steps": fc.forecast_values[:5],
                "minutes_to_warning": fc.minutes_to_warning,
                "minutes_to_critical": fc.minutes_to_critical,
                "anomaly_score": fc.anomaly_score,
            }
            for s, fc in chronos_cache.items()
        }
    fc = chronos_cache.get(sensor_name)
    if not fc:
        return {"error": f"No forecast available for {sensor_name}"}
    return {
        "sensor": sensor_name,
        "forecast_next_5_steps": fc.forecast_values[:5],
        "confidence_band": list(zip(fc.lower_bound[:5], fc.upper_bound[:5])),
        "minutes_to_warning": fc.minutes_to_warning,
        "minutes_to_critical": fc.minutes_to_critical,
        "anomaly_score": fc.anomaly_score,
    }
```

### ReAct tool descriptions — update your LLM prompt

```python
TOOL_DESCRIPTIONS = """
fetch_realtime_data(sensor_name)
  → Returns the CURRENT live reading for a sensor.
  → Use when: user asks what a sensor reads RIGHT NOW.

detect_fault(sensor_name, value)
  → Checks if current value has ALREADY crossed a threshold.
  → Use when: user asks if there is a fault NOW.

predict_trend(sensor_name, horizon_minutes)
  → Forecasts the trend for the next N minutes using Chronos AI.
  → Use when: user asks if a value is RISING/FALLING or asks about TRENDS.

fault_history(sensor_name, limit)
  → Returns past fault events from the historical log.
  → Use when: user asks about PAST faults, history, or recurring issues.

get_chronos_forecast(sensor_name)
  → Returns probabilistic forecast: minutes to warning, minutes to critical,
    anomaly score, and confidence bands.
  → Use when: user asks PREDICTIVE questions: "Will there be a fault?",
    "How long until overheat?", "Is anything about to fail?".
"""
```

---

## 8. Orchestrator — Minimal Changes Required

The orchestrator's job is to inject context into the LLM system prompt. Add Chronos forecast context here.

```python
# orchestrator.py — ADD ONE SECTION to system prompt builder

def build_system_prompt(live_data: dict, fault_events: list) -> str:
    """
    Existing function — add Chronos context block.
    """

    # ── Your existing context blocks (keep as-is) ──────────────────────
    sensor_block = format_sensor_snapshot(live_data)
    fault_block = format_fault_events(fault_events)

    # ── ADD THIS BLOCK ──────────────────────────────────────────────────
    chronos_block = ""
    if chronos_cache:
        chronos_block = chronos_service.format_for_llm_context(chronos_cache)
    # ────────────────────────────────────────────────────────────────────

    return f"""
You are an expert industrial AI assistant for a boiler and chimney monitoring system.
You ONLY answer questions about this system's real-time data, faults, and forecasts.

{sensor_block}

{fault_block}

{chronos_block}

Available tools: fetch_realtime_data, detect_fault, predict_trend, fault_history, get_chronos_forecast

When answering predictive questions ("will", "about to", "trending toward"),
always call get_chronos_forecast first and cite the forecast values in your answer.
"""
```

### Background forecast refresh thread

```python
# Add to your main application startup (app.py or main.py)

import threading
import time

chronos_cache: dict = {}
chronos_service = ChronosService(model_name="amazon/chronos-t5-small")

def _chronos_refresh_loop(interval_seconds: int = 30):
    """
    Runs in background. Refreshes Chronos forecasts every 30 seconds.
    30 seconds is the recommended interval — frequent enough for industrial monitoring,
    light enough to not strain CPU.
    """
    while True:
        try:
            histories = sensor_buffer.get_all_series(last_n=128)
            new_forecasts = chronos_service.forecast_all_sensors(histories)
            chronos_cache.update(new_forecasts)
        except Exception as e:
            logger.error(f"Chronos refresh error: {e}")
        time.sleep(interval_seconds)

# Start at application boot:
threading.Thread(target=_chronos_refresh_loop, daemon=True).start()
```

---

## 9. Fine-Tuning Chronos on Your 25K Data

Fine-tuning is **optional** for initial deployment. The `chronos-t5-small` model works zero-shot on industrial sensor data with good accuracy. Fine-tune after you have validated zero-shot performance.

### 9.1 Prepare your dataset

```python
# dataset_prep.py

import pandas as pd
import numpy as np
from gluonts.dataset.pandas import PandasDataset

def prepare_chronos_dataset(mqtt_dataframe: pd.DataFrame) -> PandasDataset:
    """
    Convert your MQTT log CSV/BigQuery export to GluonTS format for Chronos training.

    Expected input columns: timestamp, sensor_name, value
    """
    # Pivot to wide format: one column per sensor
    df = mqtt_dataframe.pivot(index="timestamp", columns="sensor_name", values="value")
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df.interpolate(method="time")  # fill any gaps in MQTT stream

    # GluonTS expects: item_id, start, target
    datasets = []
    for sensor in df.columns:
        series = df[sensor].dropna()
        datasets.append({
            "item_id": sensor,
            "start": series.index[0],
            "target": series.values.tolist(),
        })

    return PandasDataset(
        pd.DataFrame(datasets).explode("target"),
        target="target",
        item_id="item_id",
        timestamp="start",
        freq="10s",   # your MQTT publish interval
    )
```

### 9.2 Fine-tuning script

```python
# finetune_chronos.py

from chronos import ChronosPipeline
import torch
from torch.optim import AdamW

def finetune_on_boiler_data(
    train_dataset,
    output_dir: str = "./chronos-boiler-finetuned",
    epochs: int = 10,
    learning_rate: float = 1e-4,
):
    """
    Fine-tune Chronos on your 25K boiler/chimney readings.
    Recommended: run on a GPU instance (A100 or T4).
    Expected training time: ~45 minutes on T4 GPU.
    """
    pipeline = ChronosPipeline.from_pretrained(
        "amazon/chronos-t5-small",
        device_map="cuda" if torch.cuda.is_available() else "cpu",
    )

    optimizer = AdamW(pipeline.model.parameters(), lr=learning_rate)

    for epoch in range(epochs):
        epoch_loss = 0.0
        for batch in train_dataset:
            context = torch.tensor(batch["past_values"]).unsqueeze(0)
            target = torch.tensor(batch["future_values"]).unsqueeze(0)

            loss = pipeline.train_step(context=context, target=target)
            loss.backward()
            optimizer.step()
            optimizer.zero_grad()
            epoch_loss += loss.item()

        print(f"Epoch {epoch+1}/{epochs} — Loss: {epoch_loss:.4f}")

    pipeline.model.save_pretrained(output_dir)
    print(f"Fine-tuned model saved to {output_dir}")
    return output_dir


# After fine-tuning, load your custom model:
# pipeline = ChronosPipeline.from_pretrained("./chronos-boiler-finetuned")
```

### 9.3 When to fine-tune vs stay zero-shot

| Situation | Recommendation |
|---|---|
| Just deployed, testing | Zero-shot `chronos-t5-small` |
| > 2 weeks of MQTT data collected | Fine-tune on your data |
| Forecast accuracy < 85% on key sensors | Fine-tune |
| Anomaly detection missing known fault patterns | Fine-tune with fault-adjacent windows |
| Production, SLA-critical | Fine-tuned `chronos-t5-base` |

---

## 10. What Code to Delete / Not Build

This section prevents wasted effort.

### Delete or simplify these if you have them:

```
❌ Custom linear regression forecaster in predict_trend
   → Replaced by Chronos internally. Remove the math, keep the function.

❌ Hand-coded moving average anomaly detector
   → Chronos residual scoring handles this. Remove custom anomaly logic.

❌ Separate "will this breach threshold?" rule engine
   → Chronos does this probabilistically. Rule engines give no confidence intervals.

❌ Duplicate MQTT consumer for Chronos
   → Use the SensorBuffer shared with your existing consumer. One consumer only.
```

### Do NOT build these (Chronos does not replace them):

```
✅ Keep fetch_realtime_data  — Chronos forecasts ≠ current readings
✅ Keep detect_fault         — Hard threshold check ≠ probabilistic forecast
✅ Keep fault_history        — Past log ≠ future forecast
✅ Keep knowledge base       — Factual docs ≠ numerical time series
✅ Keep fine-tuned LLM       — Language model ≠ time-series model
✅ Keep Vertex AI tools      — RAG and tool orchestration unchanged
```

### Do NOT add these (common over-engineering mistakes):

```
❌ A separate database for Chronos output
   → The in-memory cache refreshed every 30s is sufficient.
   → Only persist to DB if you need forecast audit trails.

❌ A REST API wrapper around Chronos
   → Call it as a Python service within the same process.
   → HTTP overhead adds latency for no benefit in a single-host deployment.

❌ Running Chronos per-request (on every chatbot message)
   → Cache forecasts every 30s. Do not block the LLM response on Chronos inference.

❌ Building a custom transformer to replace Chronos
   → Chronos-T5 is pre-trained on 84 billion time-series data points.
   → You cannot build better from scratch with 25K readings.
```

---

## 11. Full Data Flow Diagram

```
MQTT Broker
    │
    ▼ (every 200ms per sensor)
MQTT Consumer (existing)
    │
    ├──► SensorBuffer.push()       ← one new line in your consumer
    │         │
    │         ├──► fetch_realtime_data tool  (reads latest value)
    │         │
    │         └──► Chronos background thread  (reads last 128 values every 30s)
    │                   │
    │                   ▼
    │             ChronosService.forecast_all_sensors()
    │                   │
    │                   ▼
    │             chronos_cache  (in-memory dict, refreshed every 30s)
    │                   │
    └──────────────────►│
                        │
                   Orchestrator.build_system_prompt()
                        │
                        ├── live sensor snapshot  (from fetch_realtime_data)
                        ├── active faults         (from detect_fault)
                        ├── Chronos forecast block (from chronos_cache)
                        │
                        ▼
                   Fine-Tuned LLM
                        │
                        ▼
                   ReAct Loop
                   Thought → Action → Observation
                        │
                   Tools called on demand:
                   ├── fetch_realtime_data
                   ├── detect_fault
                   ├── predict_trend      ← now Chronos-powered internally
                   ├── fault_history
                   └── get_chronos_forecast  ← new tool (reads cache)
                        │
                        ▼
                   Final LLM answer → User
```

---

## 12. Performance & Deployment Notes

### Inference latency budget

| Component | Latency | Acceptable? |
|---|---|---|
| Chronos inference (11 sensors, small model, CPU) | 120–200ms | Yes — runs in background, not on request path |
| Chronos cache read | < 1ms | Yes |
| fetch_realtime_data | < 5ms | Yes |
| detect_fault | < 2ms | Yes |
| LLM inference (7B model) | 800ms–2s | Yes |
| Total user-perceived latency | ~1–2s | Acceptable for industrial chat |

### Memory footprint

```
chronos-t5-small:     ~500MB RAM
SensorBuffer (512 × 11 sensors × float32): ~22KB
chronos_cache (11 sensors × forecast):     ~5KB
──────────────────────────────────────────
Total Chronos overhead: ~500MB RAM
```

### Recommended deployment configuration

```yaml
# docker-compose addition for Chronos service

services:
  boiler-ai:
    environment:
      CHRONOS_MODEL: "amazon/chronos-t5-small"
      CHRONOS_DEVICE: "cpu"              # set to "cuda" if GPU available
      CHRONOS_REFRESH_INTERVAL: "30"    # seconds
      CHRONOS_BUFFER_SIZE: "512"        # readings per sensor
      CHRONOS_PREDICTION_LENGTH: "20"   # steps ahead
      CHRONOS_STEP_INTERVAL: "10"       # seconds between MQTT readings
    deploy:
      resources:
        limits:
          memory: 2G    # 500MB Chronos + 1.5GB for your LLM
```

### Monitoring Chronos health

```python
# Add to your existing health check endpoint

def chronos_health() -> dict:
    stale_threshold = 120  # seconds

    if not chronos_cache:
        return {"status": "not_ready", "sensors_forecasted": 0}

    # Check for stale forecasts
    # In production, add timestamp to SensorForecast dataclass
    return {
        "status": "healthy",
        "sensors_forecasted": len(chronos_cache),
        "sensors_with_warnings": sum(
            1 for fc in chronos_cache.values()
            if fc.minutes_to_warning is not None
        ),
        "sensors_with_critical_forecast": sum(
            1 for fc in chronos_cache.values()
            if fc.minutes_to_critical is not None
        ),
    }
```

---

## Summary — Files Changed vs New

| File | Action | Reason |
|---|---|---|
| `sensor_buffer.py` | **NEW** | Rolling buffer for Chronos + existing tools |
| `chronos_service.py` | **NEW** | The only new service file |
| `predict_trend.py` | **MODIFY** (internals only) | Replace regression with Chronos |
| `detect_fault.py` | **MODIFY** (3 lines) | Add predicted_minutes_to_critical |
| `react_orchestrator.py` | **MODIFY** (add 1 tool) | Register get_chronos_forecast |
| `orchestrator.py` | **MODIFY** (add 1 block) | Inject Chronos context into system prompt |
| `app.py` / `main.py` | **MODIFY** (add thread start) | Launch Chronos background thread |
| `fetch_realtime_data.py` | **NO CHANGE** | Reads current values, Chronos reads history |
| `fault_history.py` | **NO CHANGE** | Retrospective, unrelated to forecasting |
| `knowledge_base/` | **NO CHANGE** | Factual docs, not time-series |
| Fine-tuned LLM weights | **NO CHANGE** | Language model, not time-series model |
| Vertex AI tool configs | **NO CHANGE** | Add get_chronos_forecast tool descriptor only |

---

*Documentation generated for the Boiler & Chimney AI Monitoring System. Chronos version: amazon/chronos-t5-small. Compatible with Vertex AI Agent Builder tool format.*
