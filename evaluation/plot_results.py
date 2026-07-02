"""
evaluation/plot_results.py
──────────────────────────
Reads the latest chronos_baseline_*.json evaluation report and generates
publication-quality charts for the POC presentation.

Charts generated:
  1. 6a_mape_chart.png     — MAPE per sensor (bar chart, pass/fail colour)
  2. 6c_anomaly_chart.png  — F1/Precision/Recall per sensor (grouped bars)

Run:
    python -m evaluation.plot_results
    python -m evaluation.plot_results --results-dir evaluation/results
"""
import argparse
import glob
import json
import os
from pathlib import Path

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend (works without display)
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    _MATPLOTLIB_AVAILABLE = True
except ImportError:
    _MATPLOTLIB_AVAILABLE = False
    print("⚠️  matplotlib not installed. Run: pip install matplotlib>=3.8.0")


RESULTS_DIR_DEFAULT = Path("evaluation/results")

# ── Color palette ──────────────────────────────────────────────────────────────
COLOR_PASS    = "#22c55e"   # green
COLOR_FAIL    = "#ef4444"   # red
COLOR_WARN    = "#f59e0b"   # amber
COLOR_F1      = "#6366f1"   # indigo
COLOR_PREC    = "#22c55e"   # green
COLOR_RECALL  = "#f59e0b"   # amber
BG_COLOR      = "#0f172a"   # dark navy
GRID_COLOR    = "#1e293b"
TEXT_COLOR    = "#e2e8f0"
THRESHOLD_15  = "#ef4444"   # red dashed
THRESHOLD_25  = "#f59e0b"   # amber dashed
THRESHOLD_F1  = "#ef4444"   # red dashed


def _set_dark_style() -> None:
    """Apply a clean dark theme to all matplotlib figures."""
    plt.rcParams.update({
        "figure.facecolor":  BG_COLOR,
        "axes.facecolor":    GRID_COLOR,
        "axes.edgecolor":    "#334155",
        "axes.labelcolor":   TEXT_COLOR,
        "xtick.color":       TEXT_COLOR,
        "ytick.color":       TEXT_COLOR,
        "text.color":        TEXT_COLOR,
        "grid.color":        "#1e293b",
        "grid.linestyle":    "--",
        "grid.alpha":        0.5,
        "font.family":       "sans-serif",
        "font.size":         10,
        "axes.titlesize":    13,
        "axes.titleweight":  "bold",
        "legend.facecolor":  "#1e293b",
        "legend.edgecolor":  "#334155",
        "legend.labelcolor": TEXT_COLOR,
    })


def load_latest_report(results_dir: Path) -> dict:
    """Load the most recent chronos_baseline_*.json file."""
    pattern = str(results_dir / "chronos_baseline_*.json")
    files   = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"No evaluation results found in {results_dir}. "
            "Run: python -m evaluation.chronos_eval --bucket all"
        )
    latest = files[-1]
    print(f"📂 Loading: {latest}")
    with open(latest, encoding="utf-8") as f:
        return json.load(f)


def plot_6a_mape(report: dict, out_dir: Path) -> Path | None:
    """
    Horizontal bar chart: MAPE per sensor.
    Green = pass (below threshold), Red = fail.
    Dashed vertical lines show the 15% and 25% thresholds.
    """
    bucket = report.get("buckets", {}).get("6a", {})
    results = [r for r in bucket.get("results", []) if r.get("status") == "ok"]
    if not results:
        print("⚠️  No 6a results to plot.")
        return None

    sensors    = [r["sensor"].replace("_", "\n") for r in results]
    mapes      = [r.get("mape") or 0.0 for r in results]
    thresholds = [r.get("mape_threshold", 15.0) for r in results]
    colors     = [COLOR_PASS if r.get("pass_mape") else COLOR_FAIL for r in results]

    fig, ax = plt.subplots(figsize=(14, max(6, len(sensors) * 0.55)))
    bars = ax.barh(sensors, mapes, color=colors, alpha=0.85, height=0.6)

    # Value labels
    for bar, val in zip(bars, mapes):
        ax.text(
            bar.get_width() + 0.2, bar.get_y() + bar.get_height() / 2,
            f"{val:.1f}%", va="center", ha="left",
            color=TEXT_COLOR, fontsize=8,
        )

    # Threshold lines
    ax.axvline(x=15, color=THRESHOLD_15, linestyle="--", linewidth=1.5, alpha=0.8,
               label="15% threshold (temp/pressure)")
    ax.axvline(x=25, color=THRESHOLD_25, linestyle=":",  linewidth=1.5, alpha=0.8,
               label="25% threshold (emissions)")

    # Legend
    pass_patch = mpatches.Patch(color=COLOR_PASS, label="✅ Pass")
    fail_patch = mpatches.Patch(color=COLOR_FAIL, label="❌ Fail")
    ax.legend(handles=[pass_patch, fail_patch], loc="lower right")

    pass_count = sum(1 for r in results if r.get("pass_mape"))
    ax.set_xlabel("MAPE (%)")
    ax.set_title(
        f"Chronos Forecast Accuracy — Bucket 6a (MAPE)\n"
        f"Model: {report.get('model', 'N/A')}  |  "
        f"Pass: {pass_count}/{len(results)} sensors",
    )
    ax.grid(axis="x")
    plt.tight_layout()

    out_path = out_dir / "6a_mape_chart.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"✅ Saved: {out_path}")
    return out_path


def plot_6c_anomaly(report: dict, out_dir: Path) -> Path | None:
    """
    Grouped bar chart: F1 / Precision / Recall per sensor.
    Red dashed line at F1 = 0.6 (pass threshold).
    """
    bucket     = report.get("buckets", {}).get("6c", {})
    per_sensor = bucket.get("per_sensor", [])
    if not per_sensor:
        print("⚠️  No 6c per-sensor results to plot.")
        return None

    sensors = [r["sensor"].replace("_", "\n") for r in per_sensor]
    f1s     = [r.get("f1", 0.0)        for r in per_sensor]
    precs   = [r.get("precision", 0.0) for r in per_sensor]
    recalls = [r.get("recall", 0.0)    for r in per_sensor]

    x   = np.arange(len(sensors))
    w   = 0.26  # bar width
    fig, ax = plt.subplots(figsize=(14, 5))

    ax.bar(x - w, f1s,     w, label="F1",        color=COLOR_F1,    alpha=0.9)
    ax.bar(x,     precs,   w, label="Precision",  color=COLOR_PREC,  alpha=0.9)
    ax.bar(x + w, recalls, w, label="Recall",     color=COLOR_RECALL, alpha=0.9)

    ax.axhline(y=0.6, color=THRESHOLD_F1, linestyle="--", linewidth=1.5, alpha=0.9,
               label="F1 ≥ 0.6 threshold (industry pass)")

    ax.set_xticks(x)
    ax.set_xticklabels(sensors, fontsize=8)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    avg_f1 = bucket.get("avg_f1", 0.0)
    ax.set_title(
        f"Anomaly Detection Performance — Bucket 6c\n"
        f"Avg F1={avg_f1:.3f} | "
        f"Pass: {'✅ YES' if bucket.get('pass_6c') else '❌ NO'}"
    )
    ax.legend(loc="lower right")
    ax.grid(axis="y")
    plt.tight_layout()

    out_path = out_dir / "6c_anomaly_chart.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"✅ Saved: {out_path}")
    return out_path


def plot_6b_summary(report: dict, out_dir: Path) -> Path | None:
    """Simple text + bar chart summarising fault lead-time (Bucket 6b)."""
    bucket = report.get("buckets", {}).get("6b", {})
    if bucket.get("status") != "ok":
        print("⚠️  No 6b fault lead-time data to plot.")
        return None

    fig, ax = plt.subplots(figsize=(7, 4))

    categories = ["≥ 10 min lead", "≥ 15 min lead"]
    values     = [
        bucket.get("pct_above_10min", 0.0),
        bucket.get("pct_above_15min", 0.0),
    ]
    colors = [
        COLOR_PASS if values[0] >= 70 else COLOR_FAIL,
        COLOR_PASS if values[1] >= 50 else COLOR_WARN,
    ]
    bars = ax.barh(categories, values, color=colors, alpha=0.85, height=0.4)
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
            f"{val:.1f}%", va="center", ha="left", color=TEXT_COLOR,
        )

    ax.axvline(x=70, color=THRESHOLD_15, linestyle="--", linewidth=1.5, alpha=0.8,
               label="70% pass threshold (≥10 min)")
    ax.set_xlim(0, 115)
    ax.set_xlabel("Percentage of faults (%)")
    median = bucket.get("median_lead_minutes")
    ax.set_title(
        f"Fault Lead-Time — Bucket 6b\n"
        f"Median lead: {median} min | "
        f"Pass: {'✅ YES' if bucket.get('pass_6b') else '❌ NO'}"
    )
    ax.legend()
    ax.grid(axis="x")
    plt.tight_layout()

    out_path = out_dir / "6b_leadtime_chart.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"✅ Saved: {out_path}")
    return out_path


def main(results_dir: Path) -> None:
    if not _MATPLOTLIB_AVAILABLE:
        print("Install matplotlib: pip install matplotlib>=3.8.0")
        return

    results_dir.mkdir(parents=True, exist_ok=True)
    _set_dark_style()

    try:
        report = load_latest_report(results_dir)
    except FileNotFoundError as exc:
        print(f"❌ {exc}")
        return

    print(f"\n📊 Generating evaluation charts...")
    print(f"   Model: {report.get('model', 'N/A')}")
    print(f"   Run:   {report.get('run_timestamp', 'N/A')}\n")

    plots_saved = []
    p1 = plot_6a_mape(report, results_dir)
    p2 = plot_6b_summary(report, results_dir)
    p3 = plot_6c_anomaly(report, results_dir)
    plots_saved = [p for p in [p1, p2, p3] if p is not None]

    print(f"\n✅ Done — {len(plots_saved)} chart(s) saved to {results_dir}/")
    print("   Open them in your file explorer or embed in your POC slides.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plot Chronos evaluation results")
    parser.add_argument(
        "--results-dir", type=Path, default=RESULTS_DIR_DEFAULT,
        help="Path to evaluation results directory (default: evaluation/results)",
    )
    args = parser.parse_args()
    main(args.results_dir)
