"""
evaluation/dataset_prep.py
──────────────────────────
Phase 7 (Optional) — Prepare InfluxDB data for Chronos fine-tuning

Exports 25K boiler/chimney sensor readings from InfluxDB → GluonTS format.
Required for fine-tuning chronos-t5-small on domain-specific boiler data.

Only run this AFTER Phase 6 evaluation shows MAPE > 15% OR lead-time < 10 min.
See implementation plan Phase 7 for the full decision criteria.

Usage:
    python -m evaluation.dataset_prep --days 30 --output models/training_data
"""

import argparse
import json
import logging
from pathlib import Path
from datetime import datetime, UTC

import pandas as pd
import numpy as np

from influxdb_client import InfluxDBClient

from assistant.config import (
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    SENSOR_MEASUREMENTS, ALL_SENSOR_NAMES,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

_influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)


def _get_measurement(sensor: str) -> str:
    for _, cfg in SENSOR_MEASUREMENTS.items():
        if sensor in cfg["sensors"]:
            return cfg["measurement"]
    return "boiler_sensors"


def fetch_sensor_dataframe(sensor: str, days: int = 30) -> pd.DataFrame:
    """
    Fetch sensor time-series from InfluxDB as a DataFrame.

    Returns:
        DataFrame with columns ['timestamp', 'value'], sorted oldest-first.
    """
    measurement = _get_measurement(sensor)
    query = f"""
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -{days}d)
      |> filter(fn: (r) => r["_measurement"] == "{measurement}")
      |> filter(fn: (r) => r["sensor"] == "{sensor}")
      |> filter(fn: (r) => r["_field"] == "value")
      |> sort(columns: ["_time"], desc: false)
    """
    try:
        df = _influx.query_api().query_data_frame(query)
        if df.empty:
            return pd.DataFrame(columns=["timestamp", "value"])
        df = df[["_time", "_value"]].rename(columns={"_time": "timestamp", "_value": "value"})
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", sensor, exc)
        return pd.DataFrame(columns=["timestamp", "value"])


def prepare_chronos_dataset(output_dir: str, days: int = 30) -> str:
    """
    Convert InfluxDB sensor history to GluonTS-compatible JSON Lines format.

    Each line in the output file is a JSON object:
    {
        "item_id": "sensor_name",
        "start": "ISO timestamp of first reading",
        "target": [list of float values]
    }

    This format is compatible with:
      - chronos-forecasting training scripts
      - GluonTS PandasDataset
      - AutoGluon TimeSeries

    Args:
        output_dir: Directory to write the dataset files.
        days:       How many days of history to export.

    Returns:
        Path to the written JSONL file.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    jsonl_path = out_path / f"boiler_chronos_dataset_{timestamp}.jsonl"

    total_points = 0
    written = 0

    with open(jsonl_path, "w", encoding="utf-8") as fout:
        for sensor in ALL_SENSOR_NAMES:
            logger.info("Fetching history for %s …", sensor)
            df = fetch_sensor_dataframe(sensor, days=days)

            if df.empty or len(df) < 30:
                logger.warning("Skipping %s — only %d rows", sensor, len(df))
                continue

            # Interpolate any gaps in the time-series
            df = df.set_index("timestamp")
            df = df.resample("10s").interpolate(method="time")
            df = df.dropna()
            df = df.reset_index()

            values = df["value"].tolist()
            start_ts = df["timestamp"].iloc[0].isoformat()

            record = {
                "item_id": sensor,
                "start":   start_ts,
                "target":  [round(v, 4) for v in values],
            }
            fout.write(json.dumps(record) + "\n")
            total_points += len(values)
            written += 1
            logger.info("  %s: %d points", sensor, len(values))

    # Write metadata
    meta_path = out_path / f"metadata_{timestamp}.json"
    meta = {
        "created_at":   datetime.now(UTC).isoformat(),
        "days_history": days,
        "sensors":      written,
        "total_points": total_points,
        "freq":         "10s",
        "dataset_file": str(jsonl_path),
    }
    meta_path.write_text(json.dumps(meta, indent=2))

    logger.info(
        "Dataset ready: %d sensors, %d points total → %s",
        written, total_points, jsonl_path,
    )
    return str(jsonl_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare Chronos fine-tuning dataset")
    parser.add_argument("--days", type=int, default=30, help="Days of history to export")
    parser.add_argument(
        "--output", default="models/training_data",
        help="Output directory for JSONL dataset",
    )
    args = parser.parse_args()
    prepare_chronos_dataset(output_dir=args.output, days=args.days)
