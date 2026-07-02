"""
assistant/agent/chronos_service.py
────────────────────────────────────
Phase 2 — Chronos Forecasting Service

This is the ONLY new service file needed for the Chronos integration.
It wraps the ChronosPipeline (amazon/chronos-t5-small) and provides:

  1. _fetch_influx_history()   — pulls recent float values per sensor from InfluxDB
  2. ChronosService             — forecast_sensor / forecast_all_sensors / format_for_llm_context
  3. refresh_loop()             — background thread target (Phase 3)
  4. Module-level singletons:  chronos_service, chronos_cache

Design decisions (from implementation plan):
  - InfluxDB as history source (not in-process SensorBuffer) — matches arch.
  - SENSOR_NORMAL_RANGE / SENSOR_CRITICAL_RANGE imported from config.py — single source of truth.
  - Per-request inference is PROHIBITED. Use chronos_cache only.
  - Thread is daemon so it never blocks process shutdown.
"""
import time
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional

import torch
import numpy as np
from chronos import ChronosPipeline  # type: ignore
from influxdb_client import InfluxDBClient

from assistant.config import (
    # InfluxDB connection
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    # Sensor metadata
    SENSOR_MEASUREMENTS, SENSOR_NORMAL_RANGE, SENSOR_CRITICAL_RANGE,
    ALL_SENSOR_NAMES,
    # Chronos tuning knobs
    CHRONOS_MODEL,
    CHRONOS_DEVICE,
    CHRONOS_REFRESH_INTERVAL,
    CHRONOS_PREDICTION_LENGTH,
    CHRONOS_STEP_INTERVAL,
    CHRONOS_HISTORY_MINUTES,
)

logger = logging.getLogger(__name__)


# ── InfluxDB history client ────────────────────────────────────────────────────
# Reuses the same connection pattern as predict_trend.py.
_influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
_query_api = _influx_client.query_api()


def _get_measurement_for_sensor(sensor_name: str) -> str:
    """Determine InfluxDB measurement table for a given sensor name."""
    for _group, cfg in SENSOR_MEASUREMENTS.items():
        if sensor_name in cfg["sensors"]:
            return cfg["measurement"]
    return "boiler_sensors"  # fallback


def _fetch_influx_history(sensor: str, minutes: int = CHRONOS_HISTORY_MINUTES) -> list[float]:
    """
    Fetch the last N minutes of readings for a sensor from InfluxDB.

    Returns a list of float values, sorted oldest-first (required by Chronos).
    Returns an empty list on any error.

    Guard: if `minutes` is 0 or negative InfluxDB raises
    'cannot query an empty range' (HTTP 400). We clamp to at least 1.
    """
    # ── Empty-range guard ───────────────────────────────────────────────────
    # InfluxDB Flux rejects `range(start: -0m)` with HTTP 400.
    # This can happen if CHRONOS_HISTORY_MINUTES env var is 0, or if the
    # caller passes minutes=0 (e.g. a misconfigured env on first boot).
    if minutes <= 0:
        logger.warning(
            "_fetch_influx_history called with minutes=%d for '%s' — "
            "clamping to 1 to avoid empty-range InfluxDB error.",
            minutes, sensor,
        )
        minutes = 1

    measurement = _get_measurement_for_sensor(sensor)
    query = f"""
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -{minutes}m)
      |> filter(fn: (r) => r["_measurement"] == "{measurement}")
      |> filter(fn: (r) => r["sensor"] == "{sensor}")
      |> filter(fn: (r) => r["_field"] == "value")
      |> sort(columns: ["_time"], desc: false)
    """
    try:
        tables = _query_api.query(query)
        values = []
        for table in tables:
            for record in table.records:
                v = record.get_value()
                if v is not None:
                    values.append(float(v))
        return values
    except Exception as exc:
        # Log a clean, actionable message instead of the raw InfluxDB body.
        logger.warning(
            "History fetch failed for %s: %s  "
            "(tip: verify InfluxDB is running, bucket='%s' exists, "
            "and the simulator/consumer are writing data)",
            sensor, exc, INFLUX_BUCKET,
        )
        return []


# ── Threshold map: derived from config.py (single source of truth) ─────────────
# Maps each sensor to its warning + critical levels and breach direction.
# "high" = breach when value rises above threshold.
# "low"  = breach when value falls below threshold.

def _build_threshold_map() -> dict:
    """
    Build per-sensor threshold dict from SENSOR_NORMAL_RANGE and
    SENSOR_CRITICAL_RANGE imported from config.py.

    Normal range  → (low, high)  — outside this = WARNING
    Critical range → (low, high) — outside this = CRITICAL

    Direction is inferred: if the critical-low is the binding constraint
    (i.e., sensor going DOWN is dangerous), direction = "low".
    Otherwise direction = "high".
    """
    thresholds = {}
    for sensor in ALL_SENSOR_NAMES:
        norm = SENSOR_NORMAL_RANGE.get(sensor)
        crit = SENSOR_CRITICAL_RANGE.get(sensor)
        if norm is None:
            continue

        norm_lo, norm_hi = norm

        # "Low-side dangerous" sensors: oxygen, condenser vacuum, draft (negative)
        LOW_SIDE_SENSORS = {"oxygen_level", "o2", "condenser_vacuum", "draft"}
        direction = "low" if sensor in LOW_SIDE_SENSORS else "high"

        entry = {"direction": direction}
        if direction == "high":
            # Warn when above normal band's upper edge; critical when above crit band's upper edge
            entry["warn"] = float(norm_hi)
            if crit:
                entry["critical"] = float(crit[1])
        else:
            # Warn when below normal band's lower edge; critical when below crit band's lower edge
            entry["warn"] = float(norm_lo)
            if crit:
                entry["critical"] = float(crit[0])

        thresholds[sensor] = entry
    return thresholds


THRESHOLDS = _build_threshold_map()


# ── SensorForecast dataclass ───────────────────────────────────────────────────

@dataclass
class SensorForecast:
    """
    Full probabilistic forecast output for a single sensor.

    Fields:
        sensor              — sensor name
        forecast_values     — median point forecast for next prediction_length steps
        lower_bound         — 10th percentile (pessimistic)
        upper_bound         — 90th percentile (optimistic)
        horizon_seconds     — how far ahead the forecast covers
        steps_to_warning    — step index at which warning threshold is first breached (None = never)
        steps_to_critical   — step index at which critical threshold is first breached (None = never)
        minutes_to_warning  — steps_to_warning converted to minutes (None = never)
                              NOTE: always >= 0.1 when set; 0.0 is never returned (already-breaching
                              sensors use the slope to project time-to-critical instead).
        minutes_to_critical — steps_to_critical converted to minutes (None = never)
                              NOTE: always >= 0.1 when set; use state=="critical" to detect
                              already-critical sensors.
        anomaly_score       — 0.0–1.0 (higher = more anomalous vs Chronos expected distribution)
        state               — "normal" | "warning_approaching" | "critical_approaching" | "critical"
        last_refreshed      — epoch timestamp of when this forecast was produced
    """
    sensor: str
    forecast_values: list[float]
    lower_bound: list[float]
    upper_bound: list[float]
    horizon_seconds: int
    steps_to_warning: Optional[int]
    steps_to_critical: Optional[int]
    minutes_to_warning: Optional[float]
    minutes_to_critical: Optional[float]
    anomaly_score: float
    state: str = "normal"         # "normal" | "warning_approaching" | "critical_approaching" | "critical"
    slope_per_step: float = 0.0
    breach_source: str = "none"   # "current" | "chronos" | "slope" | "none"
    last_refreshed: float = field(default_factory=time.time)

@dataclass
class SensorEvaluation:
    sensor: str
    mape: float          # Mean Absolute Percentage Error (%)
    smape: float         # Symmetric Mean Absolute Percentage Error (%)
    q_loss: float        # Average pinball loss (scaled by mean of absolute values)
    status: str          # "good" | "better" | "bad"
    last_computed: float = field(default_factory=time.time)

# ── Module-level singletons ────────────────────────────────────────────────────
# Instantiated once at import time.
# chronos_cache is updated atomically by the background thread.

chronos_service: "ChronosService" = None # Forward declared for typing

# Global forecast cache — thread-safe for simple dict swaps.
# Key: sensor_name, Value: SensorForecast
chronos_cache: dict[str, SensorForecast] = {}

# Global evaluation cache
# Key: sensor_name, Value: SensorEvaluation
chronos_eval_cache: dict[str, SensorEvaluation] = {}

# Lock for atomic cache updates
_cache_lock = threading.Lock()
_eval_lock = threading.Lock()


# ── ChronosService ─────────────────────────────────────────────────────────────

class ChronosService:
    """
    Wraps the ChronosPipeline (amazon/chronos-t5-small).

    Designed to run as a background thread alongside the FastAPI app.
    Per-request inference is PROHIBITED — use chronos_cache only.

    Usage:
        from assistant.agent.chronos_service import chronos_service, chronos_cache

        # In background thread:
        chronos_service.forecast_all_sensors(...)  → updates chronos_cache

        # In tool / orchestrator:
        fc = chronos_cache.get("main_steam_temp_boiler")
    """

    def __init__(
        self,
        model_name: str = CHRONOS_MODEL,
        device: str = CHRONOS_DEVICE,
        prediction_length: int = CHRONOS_PREDICTION_LENGTH,
        step_interval_seconds: int = CHRONOS_STEP_INTERVAL,
    ):
        logger.info("Loading Chronos model: %s on %s", model_name, device)
        print(f"⏳ Loading Chronos model '{model_name}' on device='{device}' …")

        self.pipeline = ChronosPipeline.from_pretrained(
            model_name,
            device_map=device,
            torch_dtype=torch.float32,
        )
        self.prediction_length = prediction_length
        self.step_interval_seconds = step_interval_seconds

        logger.info("Chronos ready.")
        print("✅ Chronos ready.")

    # ── Core forecast methods ──────────────────────────────────────────────

    def forecast_sensor(
        self,
        sensor_name: str,
        history: list[float],
        num_samples: int = 20,
    ) -> SensorForecast:
        """
        Forecast a single sensor stream.

        Args:
            sensor_name  — must match a key in SENSOR_NORMAL_RANGE (or will be unconstrained)
            history      — list of recent float readings (≥10, recommend 60–128)
            num_samples  — Monte Carlo samples for uncertainty estimation

        Returns:
            SensorForecast dataclass with point forecast, confidence bands,
            steps-to-threshold, and anomaly score.

        Raises:
            ValueError if fewer than 10 history points are provided.
        """
        if len(history) < 10:
            raise ValueError(
                f"Need ≥10 readings for '{sensor_name}', got {len(history)}"
            )

        context = torch.tensor(history, dtype=torch.float32).unsqueeze(0)

        # ── Chronos v2.3.0 API ──────────────────────────────────────────────────
        # v2.x: first arg is 'inputs' (positional), returns Tensor directly (no tuple)
        # v1.x had: predict(context=...) -> (Tensor, Tensor)
        forecast_tensor = self.pipeline.predict(
            context,                           # positional → 'inputs' in v2.x
            self.prediction_length,
            num_samples=num_samples,
        )

        samples = forecast_tensor[0].numpy()          # shape: (num_samples, prediction_length)
        point_forecast = np.median(samples, axis=0)   # median as point estimate
        lower = np.percentile(samples, 10, axis=0)    # 10th percentile (pessimistic)
        upper = np.percentile(samples, 90, axis=0)    # 90th percentile (optimistic)

        # ── Threshold breach detection ─────────────────────────────────────
        # Uses BOTH median AND upper/lower confidence bound:
        #   - Median crossing → high-confidence breach
        #   - 90th percentile crossing → probabilistic risk (still report)
        # Also checks current value: if already breaching now → record that fact.
        thresh = THRESHOLDS.get(sensor_name, {})
        direction = thresh.get("direction", "high")
        warn_level = thresh.get("warn")
        crit_level = thresh.get("critical")

        steps_to_warn = None
        steps_to_crit = None
        breach_source = "none"

        # Track whether the sensor is ALREADY at or past each threshold right now.
        # We do NOT set steps_to_X = 0 here anymore — that caused 0.0 min display.
        # Instead we use dedicated flags and let the forward-looking scan + slope
        # produce a meaningful ETA for the NEXT threshold (warning→critical, etc.).
        already_at_warn = False
        already_at_crit = False

        current_value = history[-1]
        if direction == "high":
            risk_series = np.maximum(point_forecast, upper)  # worst-case high
            if warn_level is not None and current_value >= warn_level:
                already_at_warn = True
            if crit_level is not None and current_value >= crit_level:
                already_at_crit = True
                breach_source = "current"
        else:
            risk_series = np.minimum(point_forecast, lower)  # worst-case low
            if warn_level is not None and current_value <= warn_level:
                already_at_warn = True
            if crit_level is not None and current_value <= crit_level:
                already_at_crit = True
                breach_source = "current"

        # Forward-looking scan: find step at which each threshold is breached.
        # If already at warn, we skip the warn search (it's already there) but
        # still scan for the critical breach step.
        for i, val in enumerate(risk_series):
            if direction == "high":
                if not already_at_warn and steps_to_warn is None and warn_level is not None and val >= warn_level:
                    steps_to_warn = i
                if not already_at_crit and steps_to_crit is None and crit_level is not None and val >= crit_level:
                    steps_to_crit = i
                    if breach_source == "none":
                        breach_source = "chronos"
            else:  # direction == "low"
                if not already_at_warn and steps_to_warn is None and warn_level is not None and val <= warn_level:
                    steps_to_warn = i
                if not already_at_crit and steps_to_crit is None and crit_level is not None and val <= crit_level:
                    steps_to_crit = i
                    if breach_source == "none":
                        breach_source = "chronos"

        # ── Slope-aware override ──────────────────────────────────────────
        # Chronos-t5-small under-reacts to monotonic ramps (outputs near-flat
        # forecast). If recent history shows clear directional drift toward
        # the threshold, project that slope linearly and check breach times.
        # This is a fallback when Chronos's median misses an obvious trend.
        slope_warn, slope_crit, slope_per_step = self._slope_breach_steps(
            history, direction, warn_level, crit_level,
            already_at_warn=already_at_warn, already_at_crit=already_at_crit,
        )
        if slope_warn is not None and (steps_to_warn is None or slope_warn < steps_to_warn):
            steps_to_warn = slope_warn
        if slope_crit is not None and (steps_to_crit is None or slope_crit < steps_to_crit):
            steps_to_crit = slope_crit
            if not already_at_crit:
                breach_source = "slope"

        # ── Compute minutes from steps ─────────────────────────────────────
        # Enforce a minimum of 0.1 min so the UI never shows "0.0 min".
        # Steps=0 would mean imminent breach; 0.1 min ≈ 6 s is a safe floor.
        secs = self.step_interval_seconds
        MIN_MINUTES = 0.1

        def _steps_to_minutes(steps: Optional[int]) -> Optional[float]:
            if steps is None:
                return None
            raw = steps * secs / 60
            return max(raw, MIN_MINUTES)

        mins_to_warn = _steps_to_minutes(steps_to_warn)
        mins_to_crit = _steps_to_minutes(steps_to_crit)

        # ── Determine state ────────────────────────────────────────────────
        # Priority: critical > critical_approaching > warning_approaching > normal
        if already_at_crit:
            state = "critical"
        elif mins_to_crit is not None:
            state = "critical_approaching"
        elif already_at_warn or mins_to_warn is not None:
            state = "warning_approaching"
        else:
            state = "normal"

        # ── Anomaly score ──────────────────────────────────────────────────
        anomaly_score = self._compute_anomaly_score(history, samples)

        return SensorForecast(
            sensor=sensor_name,
            forecast_values=point_forecast.tolist(),
            lower_bound=lower.tolist(),
            upper_bound=upper.tolist(),
            horizon_seconds=self.prediction_length * secs,
            steps_to_warning=steps_to_warn,
            steps_to_critical=steps_to_crit,
            anomaly_score=anomaly_score,
            state=state,
            slope_per_step=slope_per_step,
            breach_source=breach_source,
            minutes_to_warning=mins_to_warn,
            minutes_to_critical=mins_to_crit,
        )

    def evaluate_sensor(
        self,
        sensor_name: str,
        history: list[float],
        num_samples: int = 10,
    ) -> SensorEvaluation:
        """
        Evaluate the Chronos forecast model accuracy on a held-out test set
        (the last prediction_length steps of the history).
        """
        n_test = self.prediction_length
        if len(history) < n_test + 10:
            # Not enough history for backtesting yet (e.g. at startup).
            # Return a default placeholder.
            return SensorEvaluation(
                sensor=sensor_name,
                mape=0.0,
                smape=0.0,
                q_loss=0.0,
                status="good",
            )

        # Split into train (history up to the last n_test points) and test (the last n_test points)
        train_data = history[:-n_test]
        test_data = np.array(history[-n_test:], dtype=np.float64)

        context = torch.tensor(train_data, dtype=torch.float32).unsqueeze(0)
        forecast_tensor = self.pipeline.predict(
            context,
            n_test,
            num_samples=num_samples,
        )

        samples = forecast_tensor[0].numpy()  # shape: (num_samples, n_test)
        forecast_median = np.median(samples, axis=0)
        lower = np.percentile(samples, 10, axis=0)
        upper = np.percentile(samples, 90, axis=0)

        # Compute MAPE
        eps = 1e-8
        abs_err = np.abs(test_data - forecast_median)
        mape = float(np.mean(abs_err / (np.abs(test_data) + eps)) * 100)

        # Compute sMAPE
        smape = float(np.mean(abs_err / ((np.abs(test_data) + np.abs(forecast_median) + eps) / 2)) * 100)

        # Compute Quantile Loss (Q-Loss)
        q10_loss = np.mean(np.maximum(0.1 * (test_data - lower), (0.1 - 1) * (test_data - lower)))
        q90_loss = np.mean(np.maximum(0.9 * (test_data - upper), (0.9 - 1) * (test_data - upper)))
        mean_q_loss = float((q10_loss + q90_loss) / 2)
        
        # Scale Q-Loss by mean of absolute values
        mean_abs_test = np.mean(np.abs(test_data))
        scaled_q_loss = mean_q_loss / (mean_abs_test + eps)

        # Determine status based on MAPE
        # Good (Green): < 2.0%
        # Better / Optimal (Yellow): 2.0% - 5.0%
        # Bad / Poor (Red): >= 5.0%
        if mape < 2.0:
            status = "good"
        elif mape < 5.0:
            status = "better"
        else:
            status = "bad"

        return SensorEvaluation(
            sensor=sensor_name,
            mape=mape,
            smape=smape,
            q_loss=scaled_q_loss,
            status=status,
        )

    def forecast_all_sensors(
        self,
        sensor_histories: dict[str, list[float]],
    ) -> dict[str, SensorForecast]:
        """
        Forecast all sensors from pre-fetched history dicts.
        Called every CHRONOS_REFRESH_INTERVAL seconds by refresh_loop().

        Sensors with fewer than 10 readings are silently skipped.
        Exceptions per sensor are caught and logged — one bad sensor
        never kills the full refresh cycle.
        """
        results: dict[str, SensorForecast] = {}
        for sensor, history in sensor_histories.items():
            if len(history) < 10:
                logger.debug("Skipping %s — only %d readings", sensor, len(history))
                continue
            try:
                results[sensor] = self.forecast_sensor(sensor, history)
                logger.debug(
                    "Forecast OK: %s — warn=%.1f min, crit=%.1f min, anomaly=%.2f",
                    sensor,
                    results[sensor].minutes_to_warning or -1,
                    results[sensor].minutes_to_critical or -1,
                    results[sensor].anomaly_score,
                )
            except Exception as exc:
                logger.warning("Chronos forecast failed for %s: %s", sensor, exc)
        return results

    # ── Internal helpers ───────────────────────────────────────────────────
    def _slope_breach_steps(
        self,
        history: list[float],
        direction: str,
        warn_level: Optional[float],
        crit_level: Optional[float],
        already_at_warn: bool = False,
        already_at_crit: bool = False,
    ) -> tuple[Optional[int], Optional[int], float]:
        """
        Linear-extrapolation fallback when Chronos median is flat.

        Fits a least-squares slope over the last 30 readings. If slope is
        directionally consistent with a breach (rising for 'high' sensors,
        falling for 'low'), projects when the threshold is crossed.

        When the sensor is already at/past a threshold (already_at_warn /
        already_at_crit), the corresponding result is skipped so we never
        return steps=0 (which would produce 0.0 min in the UI).

        Returns (steps_to_warn, steps_to_crit, slope_per_step).
        Slope is always returned (0.0 if history too short).
        """
        if len(history) < 10:
            return None, None, 0.0
        window = np.asarray(history[-30:], dtype=np.float64)
        n = len(window)
        x = np.arange(n, dtype=np.float64)
        slope, intercept = np.polyfit(x, window, 1)
        current = window[-1]

        def steps_to(level: Optional[float], already_at: bool = False) -> Optional[int]:
            """
            Project how many steps until `current` (moving at `slope`/step)
            reaches `level`. Returns None if no breach predicted within horizon.
            Returns minimum 1 step (never 0) to avoid 0.0 min in the UI —
            0 is reserved exclusively for the `already_at_X` flags.
            """
            if level is None:
                return None
            if already_at:
                # Sensor is already past this threshold — don't report 0 steps;
                # let the caller handle it via the already_at_* flags.
                return None
            if direction == "high":
                if current >= level:
                    # Just reached it — return 1 step (smallest positive ETA)
                    return 1
                if slope <= 1e-4:           # not rising fast enough
                    return None
                delta = level - current
                raw = int(np.ceil(delta / slope))
                return self._cap_steps(max(raw, 1))
            else:
                if current <= level:
                    return 1
                if slope >= -1e-4:          # not falling fast enough
                    return None
                delta = current - level
                slope_abs = -slope
                raw = int(np.ceil(delta / slope_abs))
                return self._cap_steps(max(raw, 1))

        return (
            steps_to(warn_level, already_at=already_at_warn),
            steps_to(crit_level, already_at=already_at_crit),
            float(slope),
        )

    def _cap_steps(self, step: int) -> Optional[int]:
        if step < 0:
            return 0
        if step >= self.prediction_length:
            return None
        return step

    def _compute_anomaly_score(
        self,
        history: list[float],
        samples: np.ndarray,
    ) -> float:
        """
        Scores how anomalous the most recent reading is relative to the
        Chronos-expected distribution.

        Uses the first forecast step's sample distribution as the proxy for
        what the model "expected" at time T+1. Compares the actual last value
        against that distribution's IQR.

        Score: 0.0 = perfectly normal, 1.0 = extremely anomalous.
        """
        if len(history) < 2:
            return 0.0
        last_value = history[-1]
        step0_samples = samples[:, 0]
        q10 = np.percentile(step0_samples, 10)
        q90 = np.percentile(step0_samples, 90)
        band_width = max(q90 - q10, 1e-6)
        deviation = abs(last_value - float(np.median(step0_samples)))
        return float(min(deviation / (band_width * 2), 1.0))

    # ── LLM context formatter ──────────────────────────────────────────────

    def format_for_llm_context(
        self,
        forecasts: dict[str, "SensorForecast"],
        max_sensors: int = 5,
        max_chars: int = 800,
    ) -> str:
        """
        Formats the top-N most urgent Chronos forecasts as a compact text block
        to append to the user turn (NOT the system prompt — forecasts change every 30s).

        Args:
            forecasts:   dict of sensor_name → SensorForecast from chronos_cache.
            max_sensors: cap the number of sensors reported (default 5, most urgent first).
            max_chars:   hard cap on total output length in characters (default 800).
                         Ensures the block never saturates the model context window,
                         even when many sensors are in warning/critical state.

        The block is structured so urgent forecasts appear first.
        """
        # Sort by urgency: critical first (by minutes_to_critical), then warning.
        def _urgency_key(item):
            _, fc = item
            if fc.minutes_to_critical is not None:
                return (0, fc.minutes_to_critical)
            if fc.minutes_to_warning is not None:
                return (1, fc.minutes_to_warning)
            if getattr(fc, "state", "normal") == "critical":
                return (0, 0.0)
            return (2, 9999.0)

        sorted_forecasts = sorted(forecasts.items(), key=_urgency_key)

        # Only report sensors that are not normal — skip perfectly healthy ones
        # unless there are fewer than max_sensors total.
        non_normal = [
            (s, fc) for s, fc in sorted_forecasts
            if getattr(fc, "state", "normal") != "normal"
               or fc.minutes_to_warning is not None
               or fc.minutes_to_critical is not None
        ]
        top = (non_normal if non_normal else sorted_forecasts)[:max_sensors]

        lines = ["[CHRONOS FORECAST — top urgent sensors]"]
        for sensor, fc in top:
            label = sensor.replace("_", " ").title()
            state = getattr(fc, "state", "normal").upper()
            parts = [f"{label}: {state}"]
            if fc.minutes_to_critical is not None:
                parts.append(f"→ CRITICAL in {fc.minutes_to_critical:.1f} min")
            elif fc.minutes_to_warning is not None:
                parts.append(f"→ WARNING in {fc.minutes_to_warning:.1f} min")
            if fc.forecast_values:
                parts.append(f"(forecast next: {round(fc.forecast_values[0], 1)})")
            lines.append("  • " + " ".join(parts))

        if not non_normal:
            lines.append("  ✅ All sensors within normal forecast bands.")

        lines.append("[END FORECAST]")
        result = "\n".join(lines)

        # Hard cap — truncate at max_chars, add ellipsis if cut.
        if len(result) > max_chars:
            result = result[:max_chars - 3] + "..."

        return result



# ── Module-level singletons ────────────────────────────────────────────────────
# Instantiated once at import time.
# chronos_cache is updated atomically by the background thread.

chronos_service: ChronosService = ChronosService()

# Global forecast cache — thread-safe for simple dict swaps.
# Key: sensor_name, Value: SensorForecast
# Initialised empty; populated after first refresh cycle (~30s after boot).
chronos_cache: dict[str, SensorForecast] = {}

# Lock for atomic cache updates
_cache_lock = threading.Lock()

# ── Force-refresh event ────────────────────────────────────────────────────────
# Set this event to wake up refresh_loop immediately (e.g., on mode change).
# refresh_loop waits on this event with a timeout equal to interval_seconds.
_force_refresh_event = threading.Event()

# Reference to shared simulation_mode dict (injected by chatbot_api at startup).
# Used to select history window length: 2 min in normal mode (flush stale
# degradation readings), full CHRONOS_HISTORY_MINUTES in degradation mode.
_simulation_mode_ref: dict[str, str] = {"mode": "normal"}


def trigger_force_refresh() -> None:
    """
    Signal the Chronos background refresh loop to run immediately.
    Safe to call from any thread (alert_manager, API endpoint, etc.).
    """
    logger.info("Force-refresh triggered — waking up Chronos refresh loop.")
    _force_refresh_event.set()


def set_simulation_mode_ref(mode_dict: dict[str, str]) -> None:
    """
    Inject the shared simulation_mode dict from chatbot_api so refresh_loop
    can choose the appropriate InfluxDB history window.
    Called once at FastAPI startup.
    """
    global _simulation_mode_ref  # noqa: PLW0603
    _simulation_mode_ref = mode_dict


# ── Phase 3: Background refresh loop ──────────────────────────────────────────

# ── Short-history window for normal mode ──────────────────────────────────────
# After auto-recovery, degradation readings are still in InfluxDB history.
# Using a 2-minute window in normal mode flushes those ramp values out of
# Chronos context within one refresh cycle, restoring NORMAL state forecasts.
# 5-minute window in normal mode: enough for Chronos to have ≥10 readings
# even when the simulator has just been restarted (it publishes every ~0.5s).
# 2 minutes was borderline when the process was freshly started.
_NORMAL_MODE_HISTORY_MINUTES = 5
_DEGRADATION_MODE_HISTORY_MINUTES = CHRONOS_HISTORY_MINUTES


def refresh_loop(interval_seconds: int = CHRONOS_REFRESH_INTERVAL) -> None:
    """
    Background thread target (Phase 3).

    Runs forever (until process exits). Waits up to `interval_seconds` between
    cycles, but wakes up immediately when `_force_refresh_event` is set
    (triggered by mode changes or the /chronos/refresh API endpoint).

    Each cycle:
      1. Determines history window based on current simulation mode.
         - Normal mode:      2 min  (flush stale degradation readings fast)
         - Degradation mode: full CHRONOS_HISTORY_MINUTES (richer context)
      2. Fetches history for all sensors from InfluxDB.
      3. Calls ChronosService.forecast_all_sensors().
      4. Atomically updates chronos_cache.
      5. Logs cycle summary.

    Never raises — all exceptions are caught and logged.
    Thread is started as daemon in api/chatbot_api.py.
    """
    global chronos_cache  # noqa: PLW0603
    logger.info("Chronos refresh loop started (interval=%ds)", interval_seconds)
    print(f"🔄 Chronos refresh loop started — will refresh every {interval_seconds}s")

    while True:
        cycle_start = time.time()
        try:
            # Step 1: Choose history window based on current simulation mode.
            # In normal mode we use a short window (2 min) so that stale
            # degradation readings from InfluxDB do not pollute the forecast.
            current_mode = _simulation_mode_ref.get("mode", "normal")
            history_minutes = (
                _NORMAL_MODE_HISTORY_MINUTES
                if current_mode == "normal"
                else _DEGRADATION_MODE_HISTORY_MINUTES
            )

            # Step 2: Fetch histories from InfluxDB for all sensors
            histories: dict[str, list[float]] = {}
            for sensor in ALL_SENSOR_NAMES:
                values = _fetch_influx_history(sensor, minutes=history_minutes)
                if values:
                    histories[sensor] = values

            logger.debug(
                "Fetched histories for %d sensors (mode=%s, window=%dm)",
                len(histories), current_mode, history_minutes,
            )

            # Step 3: Run Chronos forecasts
            new_forecasts = chronos_service.forecast_all_sensors(histories)

            # Step 4: Atomic merge — never expose empty cache to readers.
            # Update existing keys, then drop stale keys that didn't refresh.
            with _cache_lock:
                chronos_cache.update(new_forecasts)
                stale_keys = [k for k in chronos_cache if k not in new_forecasts]
                for k in stale_keys:
                    chronos_cache.pop(k, None)

            # Step 5: Compute evaluations for all sensors
            new_evals = {}
            for sensor, history in histories.items():
                try:
                    # Compute with 10 samples to keep it fast
                    new_evals[sensor] = chronos_service.evaluate_sensor(sensor, history, num_samples=10)
                except Exception as eval_exc:
                    logger.warning("Evaluation failed for %s: %s", sensor, eval_exc)

            with _eval_lock:
                chronos_eval_cache.update(new_evals)
                stale_eval_keys = [k for k in chronos_eval_cache if k not in new_evals]
                for k in stale_eval_keys:
                    chronos_eval_cache.pop(k, None)

            # Step 6: Cycle summary log
            warn_count = sum(
                1 for fc in new_forecasts.values() if fc.minutes_to_warning is not None
            )
            crit_count = sum(
                1 for fc in new_forecasts.values() if fc.minutes_to_critical is not None
            )
            cycle_ms = round((time.time() - cycle_start) * 1000)
            logger.info(
                "Chronos refresh: %d/%d forecasted, %d evaluated | "
                "%d warnings | %d critical | %dms (mode=%s)",
                len(new_forecasts), len(ALL_SENSOR_NAMES), len(new_evals),
                warn_count, crit_count, cycle_ms, current_mode,
            )
            print(
                f"♻️  Chronos cache refreshed [{current_mode.upper()}]: "
                f"{len(new_forecasts)}/{len(ALL_SENSOR_NAMES)} sensors | "
                f"📊 {len(new_evals)} evaluated | "
                f"⚠️ {warn_count} warn | 🚨 {crit_count} critical | "
                f"⏱ {cycle_ms}ms"
            )

        except Exception as exc:
            logger.error("Chronos refresh error: %s", exc, exc_info=True)
            print(f"❌ Chronos refresh error: {exc}")

        # Wait for either the force-refresh event or the normal interval to elapse.
        # If the event fires (e.g., mode change), wake up immediately and clear it.
        _force_refresh_event.wait(timeout=interval_seconds)
        if _force_refresh_event.is_set():
            logger.info("Force-refresh event received — running immediate Chronos cycle.")
            print("⚡ Force-refresh triggered — running Chronos immediately.")
            _force_refresh_event.clear()
