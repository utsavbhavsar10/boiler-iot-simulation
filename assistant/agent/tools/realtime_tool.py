"""
Tool 1 : fetch_realtime_sensors
Fetches the latest value for every boiler and chimney sensor
from InfluxDB. Returns a formatted String the LLM reads directly.
"""

from influxdb_client import InfluxDBClient

from assistant.config import (
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    SENSOR_MEASUREMENTS, SENSOR_UNITS, SENSOR_NORMAL_RANGE,
)

# Create one client, reuse it (don't reconnect every call)
_client = InfluxDBClient(url=INFLUX_URL , token=INFLUX_TOKEN , org=INFLUX_ORG)
_query_api = _client.query_api()

def fetch_realtime_sensors():
    """
    Queries InfluxDB for the most recent value 
    of every sensor. Returns a formatted string
    showing current readings with NORMAL/OUT_OF_RANGE status for each sensor.

    Called by the agent when it needs to know current sensor status

    """

    results = {}
    for measurement, config in SENSOR_MEASUREMENTS.items():
        device  = config["device"]
        sensors = config["sensors"]

        for sensor in sensors:
            query = f"""
            from(bucket: "{INFLUX_BUCKET}")
              |> range(start: -5m)
              |> filter(fn: (r) => r["_measurement"] == "{measurement}")
              |> filter(fn: (r) => r["sensor"] == "{sensor}")
              |> filter(fn: (r) => r["_field"] == "value")
              |> last()
            """
            try:
                tables = _query_api.query(query)
                for table in tables:
                    for record in table.records:
                        results[sensor] = {
                            "value":  round(record.get_value(), 2),
                            "device": device,
                            "time":   str(record.get_time()),
                        }
            except Exception as e:
                results[sensor] = {"error": str(e)}

    if not results:
        return "ERROR: Could not fetch sensor data from InfluxDB. Check if simulator is running."

    # ── Format as readable string for LLM ─────────────────────────
    lines = [
        "=== REAL-TIME SENSOR READINGS ===",
        f"Timestamp: latest values from last 5 minutes\n",
        "BOILER SENSORS (BOILER_001):",
    ]

    boiler_sensors  = SENSOR_MEASUREMENTS["boiler_sensors"]["sensors"]
    chimney_sensors = SENSOR_MEASUREMENTS["chimney_sensors"]["sensors"]

    out_of_range = []

    for sensor in boiler_sensors:
        if sensor not in results:
            lines.append(f"  {sensor:20s}: NO DATA")
            continue
        data = results[sensor]
        if "error" in data:
            lines.append(f"  {sensor:20s}: ERROR — {data['error']}")
            continue

        val  = data["value"]
        unit = SENSOR_UNITS.get(sensor, "")
        rng  = SENSOR_NORMAL_RANGE.get(sensor)
        if rng:
            lo, hi = rng
            status = "NORMAL" if lo <= val <= hi else "⚠️ OUT_OF_RANGE"
            if lo > val or val > hi:
                out_of_range.append(f"{sensor}={val}{unit} (normal: {lo}-{hi})")
        else:
            status = ""
        lines.append(f"  {sensor:20s}: {val:8.2f} {unit:6s}  [{status}]")

    lines.append("\nCHIMNEY SENSORS (CHIMNEY_001):")
    for sensor in chimney_sensors:
        if sensor not in results:
            lines.append(f"  {sensor:20s}: NO DATA")
            continue
        data = results[sensor]
        if "error" in data:
            lines.append(f"  {sensor:20s}: ERROR — {data['error']}")
            continue

        val  = data["value"]
        unit = SENSOR_UNITS.get(sensor, "")
        rng  = SENSOR_NORMAL_RANGE.get(sensor)
        if rng:
            lo, hi = rng
            status = "NORMAL" if lo <= val <= hi else "⚠️ OUT_OF_RANGE"
            if lo > val or val > hi:
                out_of_range.append(f"{sensor}={val}{unit} (normal: {lo}-{hi})")
        else:
            status = ""
        lines.append(f"  {sensor:20s}: {val:8.2f} {unit:6s}  [{status}]")

    if out_of_range:
        lines.append(f"\n⚠️  SENSORS OUT OF RANGE: {', '.join(out_of_range)}")
    else:
        lines.append("\n✅ All sensors within normal operating range")

    return "\n".join(lines)

