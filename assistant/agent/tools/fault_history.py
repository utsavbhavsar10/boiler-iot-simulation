"""
 Tool 3 - get_fault_history
 Retrieves recent fault events from InfluxDB fault_events measurement.   
"""
from influxdb_client import InfluxDBClient

from assistant.config import (
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    SENSOR_MEASUREMENTS, SENSOR_UNITS, SENSOR_NORMAL_RANGE,
)

# Create one client, reuse it (don't reconnect every call)
_client = InfluxDBClient(url=INFLUX_URL , token=INFLUX_TOKEN , org=INFLUX_ORG)
_query_api = _client.query_api()


def get_fault_history(minutes: int = 60) -> str:
    """
    Retrieves fault events that occurred in the last N minutes
    from the boiler and chimney monitoring system.

    Use this tool when you need to:
    - Know what faults have occurred recently
    - Understand fault frequency and patterns
    - Check if a current reading is part of an ongoing fault
    - Give historical context in your answer

    Args:
        minutes: How many minutes of history to fetch (default: 60).
                 Use 30 for recent faults, 1440 for last 24 hours.

    Returns:
        String listing fault events with severity, sensor, and timestamp.
    """
    query = f"""
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -{minutes}m)
      |> filter(fn: (r) => r["_measurement"] == "fault_events")
      |> filter(fn: (r) => r["_field"] == "message")
      |> sort(columns: ["_time"], desc: true)
      |> limit(n: 20)
    """

    try:
        tables = _query_api.query(query)
        faults = []

        for table in tables:
            for record in table.records:
                faults.append({
                    "time":       str(record.get_time()),
                    "fault_code": record.values.get("fault_code", "UNKNOWN"),
                    "severity":   record.values.get("severity", "UNKNOWN"),
                    "sensor":     record.values.get("sensor", ""),
                    "message":    record.get_value(),
                })

        if not faults:
            return f"✅ No fault events in the last {minutes} minutes. System operating normally."

        # ── Count severity
        critical_count = sum(1 for f in faults if f["severity"] == "CRITICAL")
        warning_count  = sum(1 for f in faults if f["severity"] == "WARNING")

        lines = [
            f"=== FAULT HISTORY (last {minutes} minutes) ===",
            f"Total events: {len(faults)} "
            f"| Critical: {critical_count} | Warning: {warning_count}\n",
        ]

        for f in faults:
            emoji = "🚨" if f["severity"] == "CRITICAL" else "⚠️ "
            lines.append(
                f"{emoji} [{f['severity']:8s}] {f['fault_code']:25s} "
                f"| sensor: {f['sensor']:20s} | {f['time']}"
            )
            # Add message detail for most recent 5
            if len(lines) <= 8:
                lines.append(f"   ↳ {f['message']}")

        return "\n".join(lines)

    except Exception as e:
        return f"ERROR fetching fault history: {e}"