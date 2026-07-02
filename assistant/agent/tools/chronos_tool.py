"""
assistant/agent/tools/chronos_tool.py
──────────────────────────────────────
Phase 4b — New agent tool: get_chronos_forecast

Returns probabilistic forecast for one or all sensors from the in-memory
chronos_cache (populated every 30s by the background thread in Phase 3).

The LLM should call this tool when:
  - User asks PREDICTIVE questions: "Will the boiler overheat?",
    "How long until a fault?", "Is anything about to fail?",
    "What is the risk in the next 30 minutes?"
  - Questions imply uncertainty or risk ranking across multiple sensors.
  - For simple rising/falling trend questions, prefer predict_trend instead.

Return type is str (consistent with all other tools).
"""

from assistant.agent.chronos_service import chronos_cache


def get_chronos_forecast(sensor_name: str = "all") -> str:
    """
    Returns Chronos probabilistic forecast for one or all sensors.

    The forecast is drawn from the in-memory cache that the background
    thread refreshes every 30 seconds. It is never computed on-request.

    Args:
        sensor_name: Specific sensor name OR "all" for all sensors.
                     Sensor names: main_steam_flow, main_steam_temp_boiler,
                     main_steam_pressure_boiler, reheat_steam_temp_boiler,
                     superheater_desup_flow, reheater_desup_flow,
                     feedwater_temp, feedwater_flow, feedwater_pressure,
                     flue_gas_temp, oxygen_level, main_steam_temp_turbine,
                     main_steam_pressure_turbine, reheat_steam_temp_turbine,
                     reheat_steam_pressure_turbine, control_stage_pressure,
                     high_exhaust_pressure, condenser_vacuum,
                     circ_water_outlet_temp, flue_temp, co2, o2, co, draft,
                     stack_velocity.

    Returns:
        Formatted string with forecast values, confidence bands,
        minutes-to-warning, minutes-to-critical, and anomaly score.
        Returns a 'cache warming up' message if called before the first
        refresh cycle completes (~30s after startup).
    """
    if not chronos_cache:
        return (
            "Chronos forecast cache is still warming up (first refresh takes ~30s). "
            "Use predict_trend as a fallback for trend questions right now."
        )

    # ── All sensors mode ────────────────────────────────────────────────────
    if sensor_name == "all":
        lines = ["=== CHRONOS FORECAST — ALL SENSORS ==="]
        urgent: list[str] = []
        normal: list[str] = []

        for name, fc in chronos_cache.items():
            label = name.replace("_", " ").title()

            if fc.minutes_to_critical is not None:
                urgent.append(
                    f"  🚨 {label}: CRITICAL breach in "
                    f"{fc.minutes_to_critical:.1f} min | "
                    f"forecast next 5 steps: "
                    f"{[round(v, 2) for v in fc.forecast_values[:5]]} | "
                    f"confidence band: "
                    f"{round(fc.lower_bound[-1], 2)}–{round(fc.upper_bound[-1], 2)} | "
                    f"anomaly_score: {fc.anomaly_score:.2f}"
                )
            elif fc.minutes_to_warning is not None:
                urgent.append(
                    f"  ⚠️  {label}: WARNING breach in "
                    f"{fc.minutes_to_warning:.1f} min | "
                    f"forecast next 5: "
                    f"{[round(v, 2) for v in fc.forecast_values[:5]]} | "
                    f"anomaly_score: {fc.anomaly_score:.2f}"
                )
            elif fc.anomaly_score > 0.7:
                urgent.append(
                    f"  ⚠️  {label}: ANOMALY (score={fc.anomaly_score:.2f}) | "
                    f"expected range: {fc.lower_bound[0]:.2f}–{fc.upper_bound[0]:.2f}"
                )
            else:
                normal.append(
                    f"  ✅ {label}: stable | "
                    f"forecast_end: {round(fc.forecast_values[-1], 2)} | "
                    f"band: {round(fc.lower_bound[-1], 2)}–{round(fc.upper_bound[-1], 2)}"
                )

        if urgent:
            lines.append("SENSORS REQUIRING ATTENTION:")
            lines.extend(urgent)
        if normal:
            lines.append("SENSORS WITHIN NORMAL FORECAST BANDS:")
            lines.extend(normal)
        lines.append("=== END CHRONOS FORECAST ===")
        return "\n".join(lines)

    # ── Single sensor mode ──────────────────────────────────────────────────
    fc = chronos_cache.get(sensor_name)

    if fc is None:
        # Try fuzzy match — the LLM may pass partial name
        sensor_name_lower = sensor_name.lower()
        for key in chronos_cache:
            if sensor_name_lower in key or key in sensor_name_lower:
                fc = chronos_cache[key]
                sensor_name = key
                break

    if fc is None:
        available = ", ".join(sorted(chronos_cache.keys()))
        return (
            f"No Chronos forecast available for '{sensor_name}'. "
            f"Available sensors: {available}"
        )

    label = fc.sensor.replace("_", " ").title()
    horizon_min = fc.horizon_seconds // 60

    lines = [
        f"=== CHRONOS FORECAST: {label.upper()} (next {horizon_min} min) ===",
        f"Forecast next 5 steps:    {[round(v, 3) for v in fc.forecast_values[:5]]}",
        f"Forecast end value:       {round(fc.forecast_values[-1], 3)}",
        f"10th percentile (low):    {[round(v, 3) for v in fc.lower_bound[:5]]}",
        f"90th percentile (high):   {[round(v, 3) for v in fc.upper_bound[:5]]}",
        f"Confidence band (end):    {round(fc.lower_bound[-1], 3)}–{round(fc.upper_bound[-1], 3)}",
    ]

    if fc.minutes_to_warning is not None:
        lines.append(
            f"⚠️  WARNING threshold breach predicted in: "
            f"{fc.minutes_to_warning:.1f} minutes (step {fc.steps_to_warning})"
        )
    else:
        lines.append("  minutes_to_warning: None (no warning breach projected)")

    if fc.minutes_to_critical is not None:
        lines.append(
            f"🚨 CRITICAL threshold breach predicted in: "
            f"{fc.minutes_to_critical:.1f} minutes (step {fc.steps_to_critical})"
        )
    else:
        lines.append("  minutes_to_critical: None (no critical breach projected)")

    lines.append(f"Anomaly score:            {fc.anomaly_score:.3f}  (0=normal, 1=extreme)")
    lines.append("=== END FORECAST ===")
    return "\n".join(lines)
