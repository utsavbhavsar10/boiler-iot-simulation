"""
Tool 4: predict_trend  (Phase 4a — Chronos-powered internals)
─────────────────────────────────────────────────────────────
Phase 4a upgrade: internals now powered by Chronos instead of linear regression.
The function SIGNATURE and RETURN TYPE are UNCHANGED — the ReAct orchestrator
and Gemini tool schema require zero updates.

Behaviour:
  1. If chronos_cache has a forecast for the sensor → use it (primary path).
  2. If cache is empty (first ~30s after startup) → fall back to linear regression
     (_legacy_predict_trend) so the agent is never blocked during warmup.
  3. Legacy regression is kept as _legacy_predict_trend and is never deleted
     until Chronos passes Phase 6 evaluation.
"""
from influxdb_client import InfluxDBClient

from assistant.config import (
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    SENSOR_NORMAL_RANGE, SENSOR_UNITS, SENSOR_MEASUREMENTS,
)

_client    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
_query_api = _client.query_api()


# ── Primary path: Chronos-powered ──────────────────────────────────────────────

def predict_trend(sensor_name: str, window_minutes: int = 30) -> str:
    """
    Forecasts the trend of a sensor and predicts when it will reach a threshold.

    PRIMARY PATH (Chronos): reads from the background-refreshed chronos_cache.
    FALLBACK PATH (linear regression): used if cache is empty (first ~30s).

    Use this tool when:
    - A sensor is changing over time and you need to predict future risk.
    - User asks "will pressure reach critical level?", "how long before fault?"
    - You want to give a proactive warning before a fault occurs.

    For PROBABILISTIC forecasts (uncertainty, confidence bands, risk ranking
    across all sensors), prefer get_chronos_forecast instead.

    Args:
        sensor_name:    Name of the sensor to analyse.
        window_minutes: How many minutes of history to use for trend analysis
                        (only relevant for legacy fallback path).

    Returns:
        String with trend analysis, forecast values, time-to-threshold
        prediction, and confidence band (if Chronos powered).
    """
    # Import lazily to avoid circular imports at module level
    from assistant.agent.chronos_service import chronos_cache

    fc = chronos_cache.get(sensor_name)

    # Cache populated but THIS sensor missing → don't silently fall back to
    # legacy regression (different algorithm, hidden behaviour change).
    # Cache fully empty → warming up, legacy fallback is appropriate.
    if fc is None and chronos_cache:
        available = ", ".join(sorted(chronos_cache.keys()))
        return (
            f"No Chronos forecast available for '{sensor_name}'. "
            f"Sensor may have no recent InfluxDB history this cycle. "
            f"Available sensors: {available}"
        )

    if fc is not None:
        # ── Chronos-powered path ────────────────────────────────────────────
        unit = SENSOR_UNITS.get(sensor_name, "")
        label = sensor_name.replace("_", " ").upper()
        first_val = round(fc.forecast_values[0], 3)
        last_val  = round(fc.forecast_values[-1], 3)

        # Simple direction inference from start→end of forecast
        delta = last_val - first_val
        if delta > first_val * 0.02:
            trend = "RISING ↑"
        elif delta < -abs(first_val * 0.02):
            trend = "FALLING ↓"
        else:
            trend = "STABLE →"

        lines = [
            f"=== TREND ANALYSIS (Chronos-AI): {label} ===",
            f"Source:                 Chronos-T5 probabilistic forecast",
            f"Forecast start value:   {first_val} {unit}",
            f"Forecast end value:     {last_val} {unit}  (in {fc.horizon_seconds // 60} min)",
            f"Trend direction:        {trend}",
            f"Rate (start→end):       {round(last_val - first_val, 4):+.4f} {unit} over forecast",
            f"Confidence band (end):  {round(fc.lower_bound[-1], 3)}–{round(fc.upper_bound[-1], 3)} {unit}",
            f"Anomaly score:          {fc.anomaly_score:.3f} (0=normal, 1=extreme)",
        ]

        normal = SENSOR_NORMAL_RANGE.get(sensor_name)
        if normal:
            lo, hi = normal
            lines.append(f"Normal range:           {lo}–{hi} {unit}")
            in_range = lo <= first_val <= hi
            lines.append(f"Current status:         {'✅ NORMAL' if in_range else '⚠️ OUT OF RANGE'}")

        if fc.minutes_to_warning is not None:
            lines.append(
                f"\n⚠️  PREDICTION: {sensor_name} projected to breach WARNING "
                f"threshold in {fc.minutes_to_warning:.1f} minutes "
                f"(step {fc.steps_to_warning} of {len(fc.forecast_values)})."
            )
        if fc.minutes_to_critical is not None:
            lines.append(
                f"\n🚨 PREDICTION: {sensor_name} projected to breach CRITICAL "
                f"threshold in {fc.minutes_to_critical:.1f} minutes. "
                f"Immediate operator attention recommended."
            )
        if fc.minutes_to_warning is None and fc.minutes_to_critical is None:
            lines.append(
                f"\n✅ PREDICTION: No threshold breach projected within "
                f"{fc.horizon_seconds // 60} minutes at current trajectory."
            )

        lines.append(
            f"\nForecast trajectory (next 10 steps): "
            f"{[round(v, 2) for v in fc.forecast_values[:10]]}"
        )
        return "\n".join(lines)

    # ── Fallback: legacy linear regression ─────────────────────────────────
    return _legacy_predict_trend(sensor_name, window_minutes)


# ── Legacy path: linear regression (kept during ramp, removed after Phase 6 eval) ──

def _legacy_predict_trend(sensor_name: str, window_minutes: int = 30) -> str:
    """
    Original linear-regression trend analyser.
    Used when chronos_cache is empty (~first 30s of startup) as a warmup fallback.
    Not to be removed until Phase 6 MAPE evaluation confirms Chronos is better.
    """
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
        tables = _query_api.query(query)
        points = []

        for table in tables:
            for record in table.records:
                points.append({
                    "time":  record.get_time(),
                    "value": round(record.get_value(), 3),
                })

        if len(points) < 3:
            return (
                f"[FALLBACK — Chronos cache warming up] "
                f"Insufficient data for trend analysis on '{sensor_name}'. "
                f"Need at least 3 minutes of data. Only {len(points)} points found."
            )

        n      = len(points)
        values = [p["value"] for p in points]

        sum_x  = sum(range(n))
        sum_y  = sum(values)
        sum_xy = sum(i * v for i, v in enumerate(values))
        sum_xx = sum(i * i for i in range(n))

        denominator = n * sum_xx - sum_x ** 2
        slope = 0.0 if denominator == 0 else (n * sum_xy - sum_x * sum_y) / denominator

        rate_per_minute = round(slope, 4)
        current_value   = values[-1]
        unit            = SENSOR_UNITS.get(sensor_name, "")

        normal = SENSOR_NORMAL_RANGE.get(sensor_name)
        lines  = [
            f"[FALLBACK — Chronos cache warming up]",
            f"=== TREND ANALYSIS: {sensor_name.upper()} ===",
            f"Window:          Last {window_minutes} minutes ({n} data points)",
            f"Current value:   {current_value} {unit}",
            f"First value:     {values[0]} {unit}",
            f"Rate of change:  {rate_per_minute:+.4f} {unit}/minute",
        ]

        if normal:
            lo, hi = normal
            lines.append(f"Normal range:    {lo} to {hi} {unit}")
            in_range = lo <= current_value <= hi
            lines.append(f"Current status:  {'✅ NORMAL' if in_range else '⚠️ OUT OF RANGE'}")

            if rate_per_minute > 0 and current_value < hi:
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
