"""
Tool 4: predict_trend
Fetches sensor values over a time window, calculates trend,
and predicts when the sensor will reach a critical threshold.
This is the "prediction" capability of your agent.
"""
from influxdb_client import InfluxDBClient

from assistant.config import (
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    SENSOR_NORMAL_RANGE, SENSOR_UNITS, SENSOR_MEASUREMENTS,
)

_client    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
_query_api = _client.query_api()


def predict_trend(sensor_name: str, window_minutes: int = 30) -> str:
    """
    Analyses the trend of a sensor over the last N minutes and predicts
    whether it will reach a dangerous threshold, and when.

    Use this tool when:
    - A sensor is changing over time and you need to predict future risk
    - User asks "will pressure reach critical level?", "how long before fault?"
    - You want to give a proactive warning before a fault occurs

    Args:
        sensor_name:    Name of the sensor (e.g., "pressure", "temperature",
                        "water_level", "co", "flue_temp")
        window_minutes: How many minutes of history to analyse (default: 30)

    Returns:
        String with trend analysis, rate of change, and time-to-threshold prediction.
    """

    # Determine which measurement table to query by looking up the
    # sensor in SENSOR_MEASUREMENTS (boiler_sensors / turbine_sensors /
    # chimney_sensors). Defaults to boiler_sensors if unknown.
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
        tables  = _query_api.query(query)
        points  = []

        for table in tables:
            for record in table.records:
                points.append({
                    "time":  record.get_time(),
                    "value": round(record.get_value(), 3),
                })

        if len(points) < 3:
            return (
                f"Insufficient data for trend analysis on '{sensor_name}'. "
                f"Need at least 3 minutes of data. Only {len(points)} points found."
            )

        # ── Calculate trend (simple linear regression slope) ──────
        n      = len(points)
        values = [p["value"] for p in points]

        # Slope = (n*Σxy - Σx*Σy) / (n*Σx² - (Σx)²)
        # x = index (time step), y = sensor value
        sum_x  = sum(range(n))
        sum_y  = sum(values)
        sum_xy = sum(i * v for i, v in enumerate(values))
        sum_xx = sum(i * i for i in range(n))

        denominator = n * sum_xx - sum_x ** 2
        if denominator == 0:
            slope = 0.0
        else:
            slope = (n * sum_xy - sum_x * sum_y) / denominator

        # Slope is per time step (1 minute) → change per minute
        rate_per_minute = round(slope, 4)

        current_value = values[-1]
        unit          = SENSOR_UNITS.get(sensor_name, "")

        # Determine direction and risk
        normal = SENSOR_NORMAL_RANGE.get(sensor_name)
        lines  = [
            f"=== TREND ANALYSIS: {sensor_name.upper()} ===",
            f"Window:          Last {window_minutes} minutes ({n} data points)",
            f"Current value:   {current_value} {unit}",
            f"First value:     {values[0]} {unit}",
            f"Rate of change:  {rate_per_minute:+.4f} {unit}/minute",
        ]

        if normal:
            lo, hi = normal
            lines.append(f"Normal range:    {lo} to {hi} {unit}")

            # Is it currently in range?
            in_range = lo <= current_value <= hi
            lines.append(f"Current status:  {'✅ NORMAL' if in_range else '⚠️ OUT OF RANGE'}")

            # Predict time to threshold
            if rate_per_minute > 0 and current_value < hi:
                # Rising trend — when will it hit the upper threshold?
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
                # Falling trend — when will it hit the lower threshold?
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
