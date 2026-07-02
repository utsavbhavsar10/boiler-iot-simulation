"""
evaluation/chronos_eval.py
──────────────────────────
Phase 6 — Chronos Forecast Evaluation

Runs three evaluation buckets against historical InfluxDB data:

  6a. Forecast Accuracy (MAPE, sMAPE, quantile loss)
      - Holds out last 20% of historical data per sensor.
      - Runs Chronos on first 80%, compares predicted vs actual.
      - Pass criterion: MAPE < 15% for temperature/pressure, < 25% for emissions.

  6b. Fault Lead-Time
      - Replays logged fault events from InfluxDB.
      - For each fault, computes minutes_to_critical Chronos predicted beforehand.
      - Metric: median lead time, % faults with ≥10 min lead time.
      - Pass criterion: ≥70% faults with ≥10 min lead, median ≥15 min.

  6c. Anomaly Precision/Recall
      - Labels historical windows: fault-adjacent (60 min before fault) = positive.
      - Uses Chronos anomaly_score > 0.7 as detector.
      - Computes precision, recall, F1.
      - Pass criterion: F1 ≥ 0.6 zero-shot.

Usage:
    python -m evaluation.chronos_eval
    python -m evaluation.chronos_eval --sensor main_steam_temp_boiler
    python -m evaluation.chronos_eval --bucket 6a
"""

import argparse
import json
import os
import time
import logging
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

import numpy as np
from influxdb_client import InfluxDBClient

from assistant.config import (
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    SENSOR_MEASUREMENTS, SENSOR_NORMAL_RANGE, ALL_SENSOR_NAMES,
)
from assistant.agent.chronos_service import ChronosService, THRESHOLDS

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

RESULTS_DIR = Path("evaluation/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ── InfluxDB helpers ────────────────────────────────────────────────────────────

_influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
_qapi   = _influx.query_api()

def _get_measurement(sensor: str) -> str:
    for _g, cfg in SENSOR_MEASUREMENTS.items():
        if sensor in cfg["sensors"]:
            return cfg["measurement"]
    return "boiler_sensors"


def fetch_sensor_history(sensor: str, start: str, stop: str) -> list[float]:
    """
    Fetch sorted float values for a sensor between RFC3339 timestamps.
    e.g. start="-7d", stop="-1d"  or  start="2026-06-01T00:00:00Z", ...
    """
    measurement = _get_measurement(sensor)
    query = f"""
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: {start}, stop: {stop})
      |> filter(fn: (r) => r["_measurement"] == "{measurement}")
      |> filter(fn: (r) => r["sensor"] == "{sensor}")
      |> filter(fn: (r) => r["_field"] == "value")
      |> sort(columns: ["_time"], desc: false)
    """

    try:
        tables = _qapi.query(query)
        values = []
        for table in tables:
            for record in table.records:
                v = record.get_value()
                if v is not None:
                    values.append(float(v))
        return values
    except Exception as exc:
        logger.warning("History fetch failed for %s: %s", sensor, exc)
        return []

def fetch_fault_events(minutes: int = 1440 * 7) -> list[dict]:
    """Fetch fault events from InfluxDB for the last N minutes."""
    query = f"""
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -{minutes}m)
      |> filter(fn: (r) => r["_measurement"] == "fault_events")
      |> filter(fn: (r) => r["_field"] == "message")
      |> sort(columns: ["_time"], desc: false)
    """
    faults = []
    try:
        tables = _qapi.query(query)
        for table in tables:
            for record in table.records:
                faults.append({
                    "timestamp": record.get_time(),
                    "fault_code": record.values.get("fault_code", "UNKNOWN"),
                    "severity":   record.values.get("severity", "UNKNOWN"),
                    "sensor":     record.values.get("sensor", ""),
                    "message":    record.get_value(),
                })
    except Exception as exc:
        logger.warning("Fault event fetch failed: %s", exc)
    return faults


# ── Metric helpers
def compute_mape(actual: list[float], predicted: list[float]) -> Optional[float]:
    """Mean Absolute Percentage Error. Skips near-zero actual values."""
    if len(actual) != len(predicted) or not actual:
        return None
    errors = []
    for a, p in zip(actual, predicted):
        if abs(a) > 1e-6:
            errors.append(abs((a - p) / a) * 100)
    return round(float(np.mean(errors)), 3) if errors else None

def compute_smape(actual: list[float], predicted: list[float]) -> Optional[float]:
    """Symmetric MAPE — handles near-zero values better than MAPE."""
    if len(actual) != len(predicted) or not actual:
        return None
    errors = []
    for a, p in zip(actual, predicted):
        denom = (abs(a) + abs(p)) / 2
        if denom > 1e-6:
            errors.append(abs(a - p) / denom * 100)
    return round(float(np.mean(errors)), 3) if errors else None


def compute_quantile_loss(
    actual: list[float],
    lower: list[float],
    upper: list[float],
    q_low: float = 0.1,
    q_high: float = 0.9,
) -> float:
    """
    Quantile (pinball) loss for the 10th and 90th percentile forecasts.
    Lower values = better calibration.
    """
    losses = []
    for a, lo, hi in zip(actual, lower, upper):
        losses.append(max(q_low * (a - lo), (q_low - 1) * (a - lo)))
        losses.append(max(q_high * (a - hi), (q_high - 1) * (a - hi)))
    return round(float(np.mean(losses)), 4)


# ── Bucket 6a: Forecast Accuracy ────────────────────────────────────────────────

def eval_6a_forecast_accuracy(
    service: ChronosService,
    sensor: str,
    history_days: int = 7,
    train_pct: float = 0.80,
) -> dict:
    """
    Hold-out evaluation: train on first 80%, evaluate on last 20%.

    Returns:
        sensor, n_total, n_train, n_test, mape, smape, quantile_loss, pass_mape
    """
    logger.info("[6a] Evaluating forecast accuracy for %s", sensor)

    all_values = fetch_sensor_history(sensor, start=f"-{history_days}d", stop="now()")
    if len(all_values) < 30:
        logger.warning("[6a] Not enough data for %s (%d points)", sensor, len(all_values))
        return {"sensor": sensor, "status": "insufficient_data", "n_total": len(all_values)}

    split_idx = int(len(all_values) * train_pct)
    train  = all_values[:split_idx]
    actual = all_values[split_idx:]

    # Chronos needs at least 10 points
    if len(train) < 10:
        return {"sensor": sensor, "status": "train_too_short"}

    try:
        fc = service.forecast_sensor(
            sensor_name=sensor,
            history=train[-128:],  # use last 128 for context
            num_samples=50,
        )
    except Exception as exc:
        logger.error("[6a] Forecast failed for %s: %s", sensor, exc)
        return {"sensor": sensor, "status": "forecast_error", "error": str(exc)}

    # Align forecast length with actual held-out length
    min_len = min(len(actual), len(fc.forecast_values))
    actual_aligned   = actual[:min_len]
    forecast_aligned = fc.forecast_values[:min_len]
    lower_aligned    = fc.lower_bound[:min_len]
    upper_aligned    = fc.upper_bound[:min_len]

    mape  = compute_mape(actual_aligned, forecast_aligned)
    smape = compute_smape(actual_aligned, forecast_aligned)
    qloss = compute_quantile_loss(actual_aligned, lower_aligned, upper_aligned)

    # Pass criteria: temp/pressure MAPE < 15, emissions < 25
    EMISSION_SENSORS = {"co2", "co", "o2", "flue_temp", "nox_emission", "smoke_opacity"}
    threshold = 25.0 if sensor in EMISSION_SENSORS else 15.0
    pass_mape = mape is not None and mape < threshold

    result = {
        "sensor":        sensor,
        "status":        "ok",
        "n_total":       len(all_values),
        "n_train":       split_idx,
        "n_test":        len(actual),
        "mape":          mape,
        "smape":         smape,
        "quantile_loss": qloss,
        "mape_threshold": threshold,
        "pass_mape":     pass_mape,
    }

    status_icon = "✅" if pass_mape else "❌"
    logger.info(
        "[6a] %s %s | MAPE=%.2f%% (threshold=%.0f%%) | sMAPE=%.2f%% | Q-loss=%.4f",
        status_icon, sensor, mape or -1, threshold, smape or -1, qloss,
    )
    return result


# ── Bucket 6b: Fault Lead-Time ──────────────────────────────────────────────────

def eval_6b_fault_leadtime(
    service: ChronosService,
    lookback_days: int = 7,
    context_window: int = 128,
    min_lead_minutes: float = 10.0,
) -> dict:
    """
    For each logged fault, fetch the sensor history just before the fault
    and compute how many minutes Chronos predicted before actual breach.

    Returns lead-time metrics: median, pct_above_10min, pct_above_15min.
    """
    logger.info("[6b] Starting fault lead-time evaluation")

    faults = fetch_fault_events(minutes=lookback_days * 1440)
    if not faults:
        logger.warning("[6b] No fault events found in InfluxDB")
        return {"status": "no_faults", "count": 0}

    lead_times: list[float] = []
    fault_results: list[dict] = []

    for fault in faults:
        sensor = fault.get("sensor", "")
        if sensor not in ALL_SENSOR_NAMES:
            continue

        # Fetch history up to 5 minutes BEFORE the fault timestamp
        fault_ts = fault["timestamp"]
        fault_iso = fault_ts.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Use a 30-min window of data immediately before the fault
        start_iso = fault_ts.strftime("%Y-%m-%dT%H:%M:%SZ")

        history = fetch_sensor_history(
            sensor,
            start=f"-{lookback_days}d",
            stop=fault_iso,
        )

        if len(history) < 10:
            continue

        try:
            fc = service.forecast_sensor(
                sensor_name=sensor,
                history=history[-context_window:],
                num_samples=20,
            )
        except Exception as exc:
            logger.warning("[6b] Forecast failed for %s near %s: %s", sensor, fault_iso, exc)
            continue

        lead_time = fc.minutes_to_critical
        fault_results.append({
            "sensor":         sensor,
            "fault_code":     fault.get("fault_code"),
            "severity":       fault.get("severity"),
            "fault_time":     fault_iso,
            "minutes_to_critical": lead_time,
            "predicted":      lead_time is not None,
        })

        if lead_time is not None:
            lead_times.append(lead_time)

    pct_above_10 = (
        round(sum(1 for lt in lead_times if lt >= 10.0) / len(lead_times) * 100, 1)
        if lead_times else 0.0
    )
    pct_above_15 = (
        round(sum(1 for lt in lead_times if lt >= 15.0) / len(lead_times) * 100, 1)
        if lead_times else 0.0
    )
    median_lead = round(float(np.median(lead_times)), 2) if lead_times else None

    pass_6b = pct_above_10 >= 70.0 and (median_lead or 0) >= 15.0

    result = {
        "status":           "ok",
        "total_faults":     len(faults),
        "evaluated_faults": len(fault_results),
        "predicted_count":  len(lead_times),
        "median_lead_minutes":   median_lead,
        "pct_above_10min":  pct_above_10,
        "pct_above_15min":  pct_above_15,
        "pass_6b":          pass_6b,
        "fault_detail":     fault_results[:20],  # limit output
    }
    logger.info(
        "[6b] median_lead=%.1f min | ≥10min: %.1f%% | ≥15min: %.1f%% | pass=%s",
        median_lead or -1, pct_above_10, pct_above_15, pass_6b,
    )
    return result


# ── Bucket 6c: Anomaly Precision/Recall ─────────────────────────────────────────

def eval_6c_anomaly_detection(
    service: ChronosService,
    lookback_days: int = 7,
    fault_window_minutes: int = 60,
    anomaly_threshold: float = 0.7,
    context_window: int = 128,
) -> dict:
    """
    Label historical windows as:
      - Positive (anomalous): within fault_window_minutes before a logged fault
      - Negative: all other windows

    Predict anomaly using Chronos anomaly_score > anomaly_threshold.
    Compute precision, recall, F1.

    Pass criterion: F1 ≥ 0.6 zero-shot.
    """
    logger.info("[6c] Starting anomaly precision/recall evaluation")

    faults = fetch_fault_events(minutes=lookback_days * 1440)
    if not faults:
        return {"status": "no_faults"}

    # Sample windows from each sensor
    results_per_sensor: list[dict] = []

    for sensor in ALL_SENSOR_NAMES:
        history = fetch_sensor_history(sensor, start=f"-{lookback_days}d", stop="now()")
        if len(history) < context_window + 20:
            continue

        # Identify fault-adjacent (positive) windows
        fault_sensors = [f for f in faults if f.get("sensor") == sensor]
        fault_indices_positive: set = set()

        # Simple heuristic: mark the last 'fault_window_minutes * readings_per_min'
        # samples before a fault as positive. Assumes 1 reading per 10s → 6/min.
        readings_per_min = 6
        fault_window_steps = fault_window_minutes * readings_per_min

        # For each fault, mark preceding N steps as positive
        for fault in fault_sensors:
            # Approximate: we can't perfectly align without timestamps
            # Use the last fault_window_steps as positive for now
            n = len(history)
            start_idx = max(0, n - fault_window_steps)
            for i in range(start_idx, n):
                fault_indices_positive.add(i)

        # Run Chronos on multiple sliding windows
        step = max(1, context_window // 4)
        tp = fp = tn = fn = 0

        for start_idx in range(0, len(history) - context_window - 20, step):
            window = history[start_idx: start_idx + context_window]
            label = 1 if any(
                i in fault_indices_positive
                for i in range(start_idx, start_idx + context_window)
            ) else 0

            try:
                fc = service.forecast_sensor(sensor, window, num_samples=10)
                predicted = 1 if fc.anomaly_score > anomaly_threshold else 0
            except Exception:
                continue

            if predicted == 1 and label == 1:
                tp += 1
            elif predicted == 1 and label == 0:
                fp += 1
            elif predicted == 0 and label == 1:
                fn += 1
            else:
                tn += 1

        precision = round(tp / (tp + fp), 3) if (tp + fp) > 0 else 0.0
        recall    = round(tp / (tp + fn), 3) if (tp + fn) > 0 else 0.0
        f1 = round(
            2 * precision * recall / (precision + recall), 3
        ) if (precision + recall) > 0 else 0.0

        results_per_sensor.append({
            "sensor":    sensor,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": precision,
            "recall":    recall,
            "f1":        f1,
        })

    if not results_per_sensor:
        return {"status": "no_results"}

    avg_f1  = round(float(np.mean([r["f1"]        for r in results_per_sensor])), 3)
    avg_pre = round(float(np.mean([r["precision"] for r in results_per_sensor])), 3)
    avg_rec = round(float(np.mean([r["recall"]    for r in results_per_sensor])), 3)

    pass_6c = avg_f1 >= 0.6

    result = {
        "status":        "ok",
        "avg_f1":        avg_f1,
        "avg_precision": avg_pre,
        "avg_recall":    avg_rec,
        "anomaly_threshold": anomaly_threshold,
        "pass_6c":       pass_6c,
        "per_sensor":    results_per_sensor,
    }
    logger.info(
        "[6c] avg_F1=%.3f | precision=%.3f | recall=%.3f | pass=%s",
        avg_f1, avg_pre, avg_rec, pass_6c,
    )
    return result


# ── Main runner 

def run_evaluation(buckets: list[str], sensor_filter: Optional[str] = None):
    """Run selected evaluation buckets and write results to evaluation/results/."""
    logger.info("Initialising ChronosService for evaluation …")
    service = ChronosService()

    report: dict = {
        "run_timestamp": datetime.now(UTC).isoformat(),
        "model":         "amazon/chronos-t5-small",
        "buckets":       {},
    }

    if "6a" in buckets:
        sensors_to_eval = [sensor_filter] if sensor_filter else ALL_SENSOR_NAMES
        bucket_6a = []
        for sensor in sensors_to_eval:
            result = eval_6a_forecast_accuracy(service, sensor)
            bucket_6a.append(result)

        passed = [r for r in bucket_6a if r.get("pass_mape")]
        report["buckets"]["6a"] = {
            "description": "Forecast Accuracy (MAPE / sMAPE / Quantile Loss)",
            "sensors_evaluated": len(bucket_6a),
            "pass_count": len(passed),
            "overall_pass": len(passed) >= len(bucket_6a) * 0.8,
            "results": bucket_6a,
        }

    if "6b" in buckets:
        report["buckets"]["6b"] = {
            "description": "Fault Lead-Time",
            **eval_6b_fault_leadtime(service),
        }

    if "6c" in buckets:
        report["buckets"]["6c"] = {
            "description": "Anomaly Precision/Recall",
            **eval_6c_anomaly_detection(service),
        }

    # Write report
    out_path = RESULTS_DIR / f"chronos_baseline_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    logger.info("Report written to %s", out_path)

    # Also write markdown summary
    md_path = RESULTS_DIR / "chronos_baseline.md"
    _write_markdown_report(report, md_path)
    logger.info("Markdown report written to %s", md_path)

    return report


def _write_markdown_report(report: dict, path: Path):
    lines = [
        "# Chronos Evaluation Report",
        f"**Run:** {report['run_timestamp']}",
        f"**Model:** `{report['model']}`",
        "",
    ]

    for bucket_id, data in report.get("buckets", {}).items():
        lines.append(f"## Bucket {bucket_id}: {data.get('description', '')}")
        overall = data.get("overall_pass") or data.get("pass_6b") or data.get("pass_6c")
        lines.append(f"**Overall pass:** {'✅ YES' if overall else '❌ NO'}")

        if bucket_id == "6a":
            lines.append(f"Sensors evaluated: {data.get('sensors_evaluated', 0)}")
            lines.append(f"Sensors passing MAPE threshold: {data.get('pass_count', 0)}")
            lines.append("")
            lines.append("| Sensor | MAPE % | sMAPE % | Q-Loss | Pass |")
            lines.append("|--------|--------|---------|--------|------|")
            for r in data.get("results", []):
                if r.get("status") == "ok":
                    lines.append(
                        f"| {r['sensor']} | {r.get('mape', 'N/A')} | "
                        f"{r.get('smape', 'N/A')} | {r.get('quantile_loss', 'N/A')} | "
                        f"{'✅' if r.get('pass_mape') else '❌'} |"
                    )

        elif bucket_id == "6b":
            lines.append(f"- Total faults: {data.get('total_faults', 0)}")
            lines.append(f"- Evaluated: {data.get('evaluated_faults', 0)}")
            lines.append(f"- Median lead time: {data.get('median_lead_minutes')} min")
            lines.append(f"- ≥10 min lead: {data.get('pct_above_10min')}%")
            lines.append(f"- ≥15 min lead: {data.get('pct_above_15min')}%")

        elif bucket_id == "6c":
            lines.append(f"- Avg F1: {data.get('avg_f1')}")
            lines.append(f"- Avg Precision: {data.get('avg_precision')}")
            lines.append(f"- Avg Recall: {data.get('avg_recall')}")

        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chronos Evaluation Suite")
    parser.add_argument(
        "--bucket", choices=["6a", "6b", "6c", "all"], default="all",
        help="Which evaluation bucket to run (default: all)"
    )
    parser.add_argument(
        "--sensor", default=None,
        help="Limit 6a evaluation to a single sensor name"
    )
    args = parser.parse_args()

    buckets = ["6a", "6b", "6c"] if args.bucket == "all" else [args.bucket]
    run_evaluation(buckets=buckets, sensor_filter=args.sensor)
