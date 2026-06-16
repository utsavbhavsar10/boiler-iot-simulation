"""CSV Exporter - reads sensor data from InfluxDB and writes a CLEAN, flat CSV
   with meaningful column names, ready to extract directly for fine-tuning.

   InfluxDB's native CSV export is "annotated" - it has #group/#datatype/#default
   header rows and internal columns (result, table, _start, _stop) that are noise
   for ML. This script strips all of that and produces a simple table:

       time, device_id, measurement, sensor, value, unit, status

   Usage:
       python exporters/csv_exporter.py                 # last 24h -> clean_data.csv
       python exporters/csv_exporter.py 7d boiler.csv   # last 7 days -> boiler.csv
"""
import csv
import sys
from influxdb_client import InfluxDBClient

# Config
INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "my-super-secret-token-123"
INFLUX_ORG = "boiler_org"
INFLUX_BUCKET = "boiler_data"

# CLI args: range (e.g. 24h, 7d) and output file
RANGE = sys.argv[1] if len(sys.argv) > 1 else "24h"
OUTPUT_FILE = sys.argv[2] if len(sys.argv) > 2 else "clean_data.csv"

# Relative (meaningful) column names for the clean CSV
COLUMNS = ["time", "device_id", "measurement", "sensor", "value", "unit", "status"]


def export():
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    query_api = client.query_api()

    # Pull only the numeric sensor readings (the "value" field). Tags carry the
    # descriptive labels (sensor, unit, status), so no annotated header is needed.
    flux = f"""
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -{RANGE})
      |> filter(fn: (r) => r["_field"] == "value")
      |> filter(fn: (r) => r["_measurement"] == "boiler_sensors" or r["_measurement"] == "chimney_sensors")
      |> sort(columns: ["_time"])
    """

    rows = []
    for table in query_api.query(flux):
        for rec in table.records:
            rows.append({
                "time": rec.get_time().isoformat(),
                "device_id": rec.values.get("device_id", ""),
                "measurement": rec.get_measurement(),
                "sensor": rec.values.get("sensor", ""),
                "value": rec.get_value(),
                "unit": rec.values.get("unit", ""),
                "status": rec.values.get("status", ""),
            })

    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    client.close()
    print(f"Exported {len(rows)} clean rows to {OUTPUT_FILE}")
    print(f"Columns: {', '.join(COLUMNS)}")


if __name__ == "__main__":
    export()
