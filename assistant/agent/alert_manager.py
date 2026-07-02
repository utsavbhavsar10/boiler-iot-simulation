"""
assistant/agent/alert_manager.py
─────────────────────────────────
Chronos-driven alert manager for Degradation Mode.

Responsibilities:
  1. Background thread monitors chronos_cache every 15 s.
  2. When in DEGRADATION mode and any sensor shows minutes_to_critical ≤ 5:
       a. Writes a CHRONOS_CRITICAL_FORECAST fault event to InfluxDB.
       b. Sends a JSON alert to every connected /ws/alerts WebSocket client.
       c. Flips simulation_mode back to "normal"  (auto-recovery).
  3. A 120-second cooldown prevents the same sensor from firing twice.

Thread is daemon → exits automatically when the FastAPI process stops.

Usage (from api/chatbot_api.py):
    from assistant.agent.alert_manager import (
        alert_monitor_loop,
        register_websocket,
        deregister_websocket,
        simulation_mode,          # shared dict {"mode": "normal"|"degradation"}
    )
"""
import threading
import time
import logging
from datetime import datetime, UTC
from typing import Any

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from assistant.config import (
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    SENSOR_NORMAL_RANGE, SENSOR_CRITICAL_RANGE,
    SENSOR_MEASUREMENTS,
)
from assistant.agent.chronos_service import chronos_cache, trigger_force_refresh


# ── Per-sensor root-cause hints (human-readable) ──────────────────────────────
_ROOT_CAUSE: dict[str, str] = {
    "main_steam_temp_boiler":      "Superheater outlet temperature rising — likely excessive firing rate or desup spray failure.",
    "reheat_steam_temp_boiler":    "Reheater outlet over-temp — RH desup spray or attemperator malfunction.",
    "main_steam_pressure_boiler":  "Drum pressure trending high — turbine valve restriction or load imbalance.",
    "feedwater_temp":              "Feedwater temperature dropping — HP heater bypass or extraction loss.",
    "feedwater_flow":              "Feedwater flow deviation — pump degradation or control valve issue.",
    "feedwater_pressure":          "Feedwater pressure abnormal — BFP discharge problem.",
    "flue_gas_temp":               "Flue gas exit temp rising — fouled economiser / air heater leakage.",
    "oxygen_level":                "Excess O₂ drift — air register or FD fan imbalance.",
    "superheater_desup_flow":      "Excessive SH desup spray — uncontrolled steam temperature.",
    "reheater_desup_flow":         "Excessive RH desup spray — RH temperature control loss.",
    "condenser_vacuum":            "Condenser vacuum loss — air ingress or CW flow drop.",
    "circ_water_outlet_temp":      "Circ water outlet temp rising — cooling tower / CW flow degradation.",
    "flue_temp":                   "Chimney flue temp rising — incomplete combustion or air heater bypass.",
    "co":                          "Chimney CO rising — incomplete combustion / low O₂.",
    "draft":                       "Chimney draft weakening — ID fan or flue blockage.",
}


def _root_cause(sensor: str) -> str:
    return _ROOT_CAUSE.get(sensor, f"{sensor} approaching alarm threshold — investigate operating conditions.")


def _build_affected_sensors(tier: str) -> list[dict]:
    """
    Collect sensor detail entries for the alert payload.
      tier="warning"  → sensors with minutes_to_warning ≤ 5  (and no critical yet)
      tier="critical" → sensors with minutes_to_critical ≤ 5
    Each entry: {sensor, current, warn_low, warn_high, crit_low, crit_high,
                 minutes_to_warning, minutes_to_critical, cause}
    """
    out: list[dict] = []
    for sensor, fc in chronos_cache.items():
        if tier == "critical":
            if fc.minutes_to_critical is None or fc.minutes_to_critical > 5.0:
                continue
        else:  # warning
            if fc.minutes_to_warning is None or fc.minutes_to_warning > 5.0:
                continue
            # Skip if this sensor is ALSO in critical band — critical tier owns it
            if fc.minutes_to_critical is not None and fc.minutes_to_critical <= 5.0:
                continue
        norm = SENSOR_NORMAL_RANGE.get(sensor, (None, None))
        crit = SENSOR_CRITICAL_RANGE.get(sensor, (None, None))
        out.append({
            "sensor":              sensor,
            "current":             round(fc.forecast_values[0], 2) if fc.forecast_values else None,
            "warn_low":            norm[0],
            "warn_high":           norm[1],
            "crit_low":            crit[0],
            "crit_high":           crit[1],
            "minutes_to_warning":  round(fc.minutes_to_warning, 1) if fc.minutes_to_warning is not None else None,
            "minutes_to_critical": round(fc.minutes_to_critical, 1) if fc.minutes_to_critical is not None else None,
            "cause":               _root_cause(sensor),
        })
    return out

logger = logging.getLogger(__name__)

# ── Shared simulation mode dict (mutated by both API and alert manager) ────────
# FastAPI reads & writes this; alert_manager resets it on auto-recovery.
simulation_mode: dict[str, str] = {"mode": "normal"}

# ── WebSocket registry ─────────────────────────────────────────────────────────
_ws_connections: list[Any] = []
_ws_lock = threading.Lock()

# ── Live sensor fallback: InfluxDB direct query ────────────────────────────────
# Used when Chronos cache is stale to detect already-critical sensors directly.
_live_influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
_live_qapi   = _live_influx.query_api()


def _fetch_live_sensor_values() -> dict[str, float]:
    """
    Query InfluxDB for the most recent value of every sensor (last 30s).
    Returns a dict {sensor_name: float_value}.
    Used as a fallback when chronos_cache is stale or missing sensors.
    """
    result: dict[str, float] = {}
    for group_cfg in SENSOR_MEASUREMENTS.values():
        measurement = group_cfg["measurement"]
        for sensor in group_cfg["sensors"]:
            flux = f'''
            from(bucket: "{INFLUX_BUCKET}")
              |> range(start: -30s)
              |> filter(fn: (r) => r["_measurement"] == "{measurement}")
              |> filter(fn: (r) => r["sensor"] == "{sensor}")
              |> filter(fn: (r) => r["_field"] == "value")
              |> last()
            '''
            try:
                tables = _live_qapi.query(flux)
                for table in tables:
                    for record in table.records:
                        v = record.get_value()
                        if v is not None:
                            result[sensor] = float(v)
            except Exception as exc:
                logger.debug("Live sensor query failed for %s: %s", sensor, exc)
    return result


def _is_critical_live(sensor: str, value: float) -> bool:
    """Return True if value is outside the critical band for the sensor."""
    crit = SENSOR_CRITICAL_RANGE.get(sensor)
    if crit is None:
        return False
    lo, hi = crit
    return value < lo or value > hi



def register_websocket(ws: Any) -> None:
    """Register a new /ws/alerts WebSocket connection."""
    with _ws_lock:
        if ws not in _ws_connections:
            _ws_connections.append(ws)
    logger.debug("WebSocket registered. Total: %d", len(_ws_connections))


def deregister_websocket(ws: Any) -> None:
    """Remove a disconnected /ws/alerts WebSocket."""
    with _ws_lock:
        _ws_connections[:] = [c for c in _ws_connections if c is not ws]
    logger.debug("WebSocket deregistered. Total: %d", len(_ws_connections))


# ── InfluxDB write client ──────────────────────────────────────────────────────
_influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
_write_api      = _influx_client.write_api(write_options=SYNCHRONOUS)


def _write_alert_to_influx(
    sensor: str,
    minutes_to_critical: float,
    forecast_value: float,
) -> None:
    """Write auto-detected Chronos alert as a fault_event to InfluxDB."""
    try:
        point = (
            Point("fault_events")
            .tag("fault_code", "CHRONOS_CRITICAL_FORECAST")
            .tag("severity", "CRITICAL")
            .tag("sensor", sensor)
            .tag("source", "chronos_auto_alert")
            .field(
                "message",
                f"Chronos predicts {sensor} will breach CRITICAL in "
                f"{minutes_to_critical:.1f} min (forecast: {forecast_value:.2f})",
            )
            .field("minutes_to_critical", float(minutes_to_critical))
            .field("forecast_value", float(forecast_value))
            .time(datetime.now(UTC))
        )
        _write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
        logger.info("Alert written to InfluxDB — sensor=%s, ttc=%.1f min", sensor, minutes_to_critical)
    except Exception as exc:
        logger.error("Failed to write alert to InfluxDB: %s", exc)


async def _broadcast_alert_async(payload: dict) -> None:
    """Async helper: send alert JSON to all connected WebSocket clients."""
    dead: list[Any] = []
    with _ws_lock:
        clients = list(_ws_connections)
    for ws in clients:
        try:
            await ws.send_json(payload)
        except Exception as exc:
            logger.debug("WebSocket send failed (%s) — marking dead", exc)
            dead.append(ws)
    for ws in dead:
        deregister_websocket(ws)


def _broadcast_alert_sync(payload: dict) -> None:
    """
    Synchronous wrapper around _broadcast_alert_async.
    Called from the background thread (not async context).
    Creates a new event loop in this thread to run the coroutine.
    """
    import asyncio
    dead: list[Any] = []
    with _ws_lock:
        clients = list(_ws_connections)
    if not clients:
        logger.debug("No WebSocket clients connected — skipping broadcast")
        return
    # Run async send in a tight loop (no full event loop needed for simple JSON send)
    for ws in clients:
        try:
            # Starlette WebSocket.send_json is a coroutine; run it synchronously.
            loop = asyncio.new_event_loop()
            loop.run_until_complete(ws.send_json(payload))
            loop.close()
        except Exception as exc:
            logger.debug("WebSocket broadcast failed: %s", exc)
            dead.append(ws)
    for ws in dead:
        deregister_websocket(ws)


# ── Alert state (cooldown tracking, per-tier) ─────────────────────────────────
_last_alert_sensor: str | None  = None
_last_alert_time:   float       = 0.0
_last_warn_sensor:  str | None  = None
_last_warn_time:    float       = 0.0
_ALERT_COOLDOWN_SECONDS         = 120  # don't re-fire same sensor within 2 min
_WARN_COOLDOWN_SECONDS          = 90   # warning tier cooldown


def _trigger_auto_recovery(sensor: str) -> dict:
    """
    Reset simulation mode to NORMAL and return the alert payload
    that should be broadcast to dashboard clients.
    Also triggers an immediate Chronos refresh so the forecast cache
    switches to the 2-minute history window and purges stale degradation
    readings within one cycle.
    """
    simulation_mode["mode"] = "normal"
    logger.warning(
        "🔄 AUTO-RECOVERY: %s critical forecast detected — mode reset to NORMAL", sensor
    )
    print(
        f"🔄 AUTO-RECOVERY activated — {sensor} was approaching CRITICAL. "
        f"Simulation mode → NORMAL."
    )
    # Wake up Chronos refresh loop immediately so it picks up the normal-mode
    # 2-minute history window and clears stale degradation forecast data.
    trigger_force_refresh()
    return {
        "type":               "chronos_alert",
        "sensor":             sensor,
        "auto_recovery":      True,
        "timestamp":          datetime.now(UTC).isoformat(),
    }


# ── Main background loop ───────────────────────────────────────────────────────

def alert_monitor_loop(check_interval_seconds: int = 15) -> None:
    """
    Background thread target.

    Runs forever (daemon thread — exits with the process).
    Every `check_interval_seconds`:
      1. Checks if simulation is in DEGRADATION mode.
      2. Scans chronos_cache for sensors with minutes_to_critical ≤ 5.
      3. Fires alert pipeline (InfluxDB write + WebSocket broadcast + auto-recovery)
         for the most urgent sensor (lowest minutes_to_critical).
      4. Respects per-sensor 120s cooldown.
    """
    global _last_alert_sensor, _last_alert_time, _last_warn_sensor, _last_warn_time

    logger.info(
        "Alert monitor started — checking every %ds for Chronos warning/critical forecasts",
        check_interval_seconds,
    )
    print(f"🔔 Alert monitor started (interval={check_interval_seconds}s)")

    while True:
        try:
            if simulation_mode.get("mode") == "degradation":
                now = time.time()

                # ── Tier 0: LIVE CRITICAL CHECK (bypasses Chronos cache) ─────────────────
                # Safety net: Chronos can be stale (>120s cache age) or Chronos-t5-small
                # may under-predict extreme ramp values. We read InfluxDB directly for
                # the latest sensor values and fire auto-recovery if ANY sensor is already
                # past its critical threshold — regardless of what Chronos says.
                # Cooldown: same sensor won't re-fire within ALERT_COOLDOWN_SECONDS.
                try:
                    live_values = _fetch_live_sensor_values()
                    live_critical = [
                        (sensor, val)
                        for sensor, val in live_values.items()
                        if _is_critical_live(sensor, val)
                    ]
                    if live_critical:
                        # Pick most critical (largest deviation from band edge)
                        def _deviation(item):
                            s, v = item
                            crit = SENSOR_CRITICAL_RANGE.get(s)
                            if not crit:
                                return 0.0
                            lo, hi = crit
                            return max(lo - v, v - hi, 0.0)
                        live_critical.sort(key=_deviation, reverse=True)
                        sensor, live_val = live_critical[0]

                        live_cooldown_ok = (
                            sensor != _last_alert_sensor
                            or (now - _last_alert_time) > _ALERT_COOLDOWN_SECONDS
                        )
                        if live_cooldown_ok:
                            crit_range = SENSOR_CRITICAL_RANGE.get(sensor, (None, None))
                            norm_range = SENSOR_NORMAL_RANGE.get(sensor, (None, None))
                            logger.warning(
                                "🚨 LIVE CRITICAL (Chronos bypass): sensor=%s | value=%.2f | crit_band=[%s, %s]",
                                sensor, live_val,
                                crit_range[0] if crit_range else "?",
                                crit_range[1] if crit_range else "?",
                            )

                            _write_alert_to_influx(sensor, 0.1, live_val)

                            payload = {
                                "type":                "chronos_alert",
                                "severity":            "CRITICAL",
                                "sensor":              sensor,
                                "state":               "critical",
                                "minutes_to_critical": 0.1,
                                "minutes_to_warning":  None,
                                "anomaly_score":       1.0,
                                "forecast_value":      round(live_val, 2),
                                "slope_per_step":      0.0,
                                "breach_source":       "live_sensor",
                                "auto_recovery":       True,
                                "cause": (
                                    _root_cause(sensor) +
                                    f" [LIVE: {round(live_val, 2)} is outside critical band "
                                    f"{crit_range[0] if crit_range else '?'}–"
                                    f"{crit_range[1] if crit_range else '?'}]"
                                ),
                                "affected_sensors": [{
                                    "sensor":              sensor,
                                    "current":             round(live_val, 2),
                                    "warn_low":            norm_range[0] if norm_range else None,
                                    "warn_high":           norm_range[1] if norm_range else None,
                                    "crit_low":            crit_range[0] if crit_range else None,
                                    "crit_high":           crit_range[1] if crit_range else None,
                                    "minutes_to_warning":  None,
                                    "minutes_to_critical": 0.1,
                                    "cause":               _root_cause(sensor),
                                }],
                                "timestamp": datetime.now(UTC).isoformat(),
                            }

                            _last_alert_sensor = sensor
                            _last_alert_time   = now

                            _trigger_auto_recovery(sensor)
                            _broadcast_alert_sync(payload)
                            # Skip Chronos-cache tiers this cycle — live check already handled it
                            time.sleep(check_interval_seconds)
                            continue

                except Exception as live_exc:
                    logger.debug("Live sensor check failed (non-critical): %s", live_exc)

                # ── Tier 1: CRITICAL (minutes_to_critical ≤ 5 OR already at critical) ───
                critical_sensors = [
                    (fc.minutes_to_critical if fc.minutes_to_critical is not None else 0.0, sensor, fc)
                    for sensor, fc in chronos_cache.items()
                    if (
                        # Approaching critical within 5 min
                        (fc.minutes_to_critical is not None and fc.minutes_to_critical <= 5.0)
                        # OR already at critical right now
                        or getattr(fc, "state", None) == "critical"
                    )
                ]

                if critical_sensors:
                    critical_sensors.sort()
                    minutes, sensor, fc = critical_sensors[0]

                    cooldown_ok = (
                        sensor != _last_alert_sensor
                        or (now - _last_alert_time) > _ALERT_COOLDOWN_SECONDS
                    )

                    if cooldown_ok:
                        forecast_val = fc.forecast_values[0] if fc.forecast_values else 0.0
                        sensor_state = getattr(fc, "state", "critical_approaching")
                        # Clamp to >=0.1 so the UI never displays "0.0 min".
                        # For sensors already AT critical (state=="critical"), minutes==0.0
                        # from the list comprehension default — we show 0.1 (imminent).
                        display_minutes = max(minutes, 0.1) if minutes is not None else 0.1
                        logger.warning(
                            "🚨 CHRONOS CRITICAL: sensor=%s | ttc=%.1f min | state=%s | anomaly=%.2f",
                            sensor, display_minutes, sensor_state, fc.anomaly_score,
                        )

                        _write_alert_to_influx(sensor, display_minutes, forecast_val)

                        payload = {
                            "type":                "chronos_alert",
                            "severity":            "CRITICAL",
                            "sensor":              sensor,
                            "state":               sensor_state,
                            "minutes_to_critical": round(display_minutes, 1),
                            "minutes_to_warning":  round(fc.minutes_to_warning, 1) if fc.minutes_to_warning is not None else None,
                            "anomaly_score":       round(fc.anomaly_score, 3),
                            "forecast_value":      round(forecast_val, 2),
                            "slope_per_step":      round(fc.slope_per_step, 4),
                            "breach_source":       fc.breach_source,
                            "upper_bound_end":     round(fc.upper_bound[-1], 2) if fc.upper_bound else None,
                            "lower_bound_end":     round(fc.lower_bound[-1], 2) if fc.lower_bound else None,
                            "auto_recovery":       True,
                            "cause":               _root_cause(sensor),
                            "affected_sensors":    _build_affected_sensors("critical"),
                            "timestamp":           datetime.now(UTC).isoformat(),
                        }

                        _last_alert_sensor = sensor
                        _last_alert_time   = now

                        _trigger_auto_recovery(sensor)
                        _broadcast_alert_sync(payload)

                else:
                    # ── Tier 2: WARNING (minutes_to_warning ≤ 5) ─────────────────────────
                    # Only fire if no critical pending; gives operator lead time.
                    # Exclude sensors that are:
                    #   - already past warning (state == "warning_approaching" means approaching,
                    #     but state == "critical" or "critical_approaching" means beyond warning).
                    #   - OR sensors where minutes_to_warning is None/zero (already in warning band).
                    warning_sensors = [
                        (fc.minutes_to_warning, sensor, fc)
                        for sensor, fc in chronos_cache.items()
                        if (
                            fc.minutes_to_warning is not None
                            and fc.minutes_to_warning > 0.05   # exclude already-at-warning (0.0/0.1)
                            and fc.minutes_to_warning <= 5.0
                            and (fc.minutes_to_critical is None or fc.minutes_to_critical > 5.0)
                            and getattr(fc, "state", "normal") not in ("critical", "critical_approaching")
                        )
                    ]

                    if warning_sensors:
                        warning_sensors.sort()
                        minutes, sensor, fc = warning_sensors[0]

                        warn_cooldown_ok = (
                            sensor != _last_warn_sensor
                            or (now - _last_warn_time) > _WARN_COOLDOWN_SECONDS
                        )

                        if warn_cooldown_ok:
                            forecast_val = fc.forecast_values[0] if fc.forecast_values else 0.0
                            sensor_state = getattr(fc, "state", "warning_approaching")
                            logger.warning(
                                "⚠️  CHRONOS WARNING: sensor=%s | ttw=%.1f min | state=%s | anomaly=%.2f",
                                sensor, minutes, sensor_state, fc.anomaly_score,
                            )

                            payload = {
                                "type":               "chronos_alert",
                                "severity":           "WARNING",
                                "sensor":             sensor,
                                "state":              sensor_state,
                                "minutes_to_warning": round(minutes, 1),
                                "anomaly_score":      round(fc.anomaly_score, 3),
                                "forecast_value":     round(forecast_val, 2),
                                "slope_per_step":     round(fc.slope_per_step, 4),
                                "breach_source":      fc.breach_source,
                                "upper_bound_end":    round(fc.upper_bound[-1], 2) if fc.upper_bound else None,
                                "lower_bound_end":    round(fc.lower_bound[-1], 2) if fc.lower_bound else None,
                                "auto_recovery":      False,
                                "cause":              _root_cause(sensor),
                                "affected_sensors":   _build_affected_sensors("warning"),
                                "timestamp":          datetime.now(UTC).isoformat(),
                            }

                            _last_warn_sensor = sensor
                            _last_warn_time   = now

                            _broadcast_alert_sync(payload)

        except Exception as exc:
            logger.error("Alert monitor error: %s", exc, exc_info=True)

        time.sleep(check_interval_seconds)
