"""Fault Detector - Consumer
Subscribes to all MQTT sensor topics , applies 
threshold rules, and raises fault alerts when 
values go out of range.

Runs independently alongside influx_consumer.py
"""

import os
import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient , Point
from influxdb_client.client.write_api import SYNCHRONOUS
import json
from datetime import datetime , UTC

# Config — read from environment so Docker Compose can inject service names
MQTT_HOST    = os.getenv("MQTT_HOST",    "localhost")
MQTT_PORT    = int(os.getenv("MQTT_PORT", "1883"))
INFLUX_URL   = os.getenv("INFLUX_URL",   "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "my-super-secret-token-123")
INFLUX_ORG   = os.getenv("INFLUX_ORG",   "boiler_org")
INFLUX_BUCKET= os.getenv("INFLUX_BUCKET","boiler_data")

# Threshold Rules
# Format: sensor_name -> (min_ok, max_ok, severity, fault_code, unit)
# Keys MUST match the `sensor` value published by the simulators
# (the dict keys in boiler_simulator.NORMAL / chimney_simulator.NORMAL),
# otherwise check_threshold() never matches and no fault is ever raised.
BOILER_RULES = {
    "main_steam_flow":              (800, 1000, "WARNING",  "ABNORMAL_MAIN_STEAM_FLOW",   "t/h"),
    "main_steam_temp_boiler":       (535, 545,  "CRITICAL", "ABNORMAL_MAIN_STEAM_TEMP",   "C"),
    "main_steam_pressure_boiler":   (16.0, 17.5,"CRITICAL", "ABNORMAL_MAIN_STEAM_PRESS",  "MPa"),
    "reheat_steam_temp_boiler":     (535, 545,  "WARNING",  "ABNORMAL_REHEAT_TEMP",       "C"),
    "superheater_desup_flow":       (10, 40,    "WARNING",  "ABNORMAL_DESUP_SPRAY",       "t/h"),
    "reheater_desup_flow":          (0, 15,     "WARNING",  "ABNORMAL_REHEAT_DESUP",      "t/h"),
    "feedwater_temp":               (270, 285,  "WARNING",  "ABNORMAL_FEEDWATER_TEMP",    "C"),
    "feedwater_flow":               (800, 1000, "CRITICAL", "LOW_FEEDWATER_FLOW",         "t/h"),
    "feedwater_pressure":           (18.0, 20.0,"CRITICAL", "LOW_FEEDWATER_PRESSURE",     "MPa"),
    "flue_gas_temp":                (120, 140,  "WARNING",  "HIGH_FLUE_GAS_TEMP",         "C"),
    "oxygen_level":                 (3, 5,      "WARNING",  "ABNORMAL_OXYGEN",            "%"),
    "main_steam_temp_turbine":      (530, 540,  "WARNING",  "ABNORMAL_TURBINE_TEMP",      "C"),
    "main_steam_pressure_turbine":  (15.5, 17.0,"WARNING",  "ABNORMAL_TURBINE_PRESS",     "MPa"),
    "reheat_steam_temp_turbine":    (530, 540,  "WARNING",  "ABNORMAL_RH_TURBINE_TEMP",   "C"),
    "reheat_steam_pressure_turbine":(3.0, 4.0,  "WARNING",  "ABNORMAL_RH_TURBINE_PRESS",  "MPa"),
    "control_stage_pressure":       (10.0, 13.0,"WARNING",  "ABNORMAL_CONTROL_STAGE",     "MPa"),
    "high_exhaust_pressure":        (3.0, 4.0,  "WARNING",  "ABNORMAL_EXHAUST_PRESS",     "MPa"),
    "condenser_vacuum":             (4.0, 7.0,  "CRITICAL", "CONDENSER_VACUUM_LOSS",      "kPa"),
    "circ_water_outlet_temp":       (25, 35,    "WARNING",  "HIGH_CIRC_WATER_TEMP",       "C"),
}

CHIMNEY_RULES = {
    "flue_temp":      (150, 250, "WARNING",  "HIGH_FLUE_TEMP",   "C"),
    "co2":            (8, 14,    "WARNING",  "ABNORMAL_CO2",     "%"),
    "o2":             (3, 8,     "WARNING",  "ABNORMAL_O2",      "%"),
    "co":             (0, 50,    "CRITICAL", "HIGH_CO",          "ppm"),
    "draft":          (-5, -2,   "WARNING",  "ABNORMAL_DRAFT",   "Pa"),
    "stack_velocity": (3, 8,     "WARNING",  "ABNORMAL_STACK",   "m/s"),
}

# InfluxDB write client
influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx_client.write_api(write_options=SYNCHRONOUS)

# Track recent faults to avoid duplicate alerts (cooldown per sensor)
fault_cooldown = {}   # {sensor_key: last_fault_timestamp}
COOLDOWN_SECONDS = 30


def check_threshold(device_id: str, sensor: str, value: float, rules: dict) -> dict | None:
    """
    Check if a sensor value violates a threshold rule.
    Returns a fault dict if violated, None if normal.
    """
    if sensor not in rules:
        return None

    min_ok, max_ok, severity, fault_code, unit = rules[sensor]

    # Value is within normal range — no fault
    if min_ok <= value <= max_ok:
        return None

    # Check cooldown — don't spam the same fault every 500ms
    cooldown_key = f"{device_id}_{sensor}"
    now = datetime.now(UTC).timestamp()
    last_fault_time = fault_cooldown.get(cooldown_key, 0)

    if now - last_fault_time < COOLDOWN_SECONDS:
        return None  # Still in cooldown, skip

    # Record this fault time
    fault_cooldown[cooldown_key] = now

    # Determine direction
    if value > max_ok:
        direction = f"above maximum ({max_ok} {unit})"
    else:
        direction = f"below minimum ({min_ok} {unit})"

    return {
        "device_id":       device_id,
        "fault_code":      fault_code,
        "severity":        severity,
        "sensor":          sensor,
        "value":           value,
        "unit":            unit,
        "normal_min":      min_ok,
        "normal_max":      max_ok,
        "direction":       direction,
        "timestamp":       datetime.now(UTC),
        "message": (
            f"{severity}: {fault_code} on {device_id}. "
            f"{sensor} = {value} {unit} is {direction}. "
            f"Normal range: {min_ok}–{max_ok} {unit}."
        ),
    }


def handle_fault(client, fault: dict):
    """Log fault to InfluxDB and publish alert to MQTT."""

    # ── Write to InfluxDB ────────────────────────────────────────
    point = (
        Point("fault_events")
        .tag("device_id",  fault["device_id"])
        .tag("fault_code", fault["fault_code"])
        .tag("severity",   fault["severity"])
        .tag("sensor",     fault["sensor"])
        .field("value",          float(fault["value"]))
        .field("normal_min",     float(fault["normal_min"]))
        .field("normal_max",     float(fault["normal_max"]))
        .field("message",        fault["message"])
        .field("affected_sensor", fault["sensor"])
        .time(fault["timestamp"])
    )
    write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)

    # ── Publish fault alert back to MQTT ────────────────────────
    # Other consumers (e.g. a notification service) can subscribe to system/faults
    client.publish("system/faults", json.dumps(fault, default=str), qos=2)

    # ── Console log ─────────────────────────────────────────────
    emoji = "🚨" if fault["severity"] == "CRITICAL" else "⚠️ "
    print(f"{emoji} {fault['message']}")


def on_connect(mqtt_client, userdata, flags, rc):
    if rc == 0:
        mqtt_client.subscribe("boiler/#", qos=1)
        mqtt_client.subscribe("chimney/#", qos=1)
        print("✅ Fault detector connected — watching all sensors")


def on_message(mqtt_client, userdata, message):
    """Process every incoming sensor message through threshold rules."""
    try:
        payload = json.loads(message.payload.decode("utf-8"))
        topic   = message.topic

        # Only process individual sensor readings (not status summaries)
        if "value" not in payload:
            return

        device_id   = payload.get("device_id", "UNKNOWN")
        sensor_name = payload.get("sensor", "")
        value       = float(payload["value"])

        # Pick the right ruleset based on topic prefix
        if topic.startswith("boiler"):
            fault = check_threshold(device_id, sensor_name, value, BOILER_RULES)
        elif topic.startswith("chimney"):
            fault = check_threshold(device_id, sensor_name, value, CHIMNEY_RULES)
        else:
            return

        if fault:
            handle_fault(mqtt_client, fault)

    except Exception as e:
        print(f"❌ Fault detector error: {e}")


# ─── START ───────────────────────────────────────────────────────
client = mqtt.Client(client_id="fault_detector")
client.on_connect = on_connect
client.on_message = on_message
client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)

print("🔍 Fault detector started. Monitoring all thresholds...")
client.loop_forever()