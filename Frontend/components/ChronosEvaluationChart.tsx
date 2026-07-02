"use client";
import { useEffect, useState, useMemo } from "react";
import { fetchChronosEvaluation, SensorEvaluation } from "@/lib/api";
import { prettyName } from "@/lib/sensors";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { ShieldCheck, Info, RefreshCw, Sparkles, TrendingUp } from "lucide-react";
import clsx from "clsx";

const REFRESH_MS = 10_000;

export function ChronosEvaluationChart() {
  const [evals, setEvals] = useState<Record<string, SensorEvaluation> | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const fetchEvalData = async () => {
    try {
      const res = await fetchChronosEvaluation();
      if ("error" in res) {
        // Cache warming up
        setEvals(null);
      } else {
        setEvals(res.evaluations);
        setErr(null);
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEvalData();
    const interval = setInterval(fetchEvalData, REFRESH_MS);
    return () => clearInterval(interval);
  }, []);

  const sortedEvals = useMemo(() => {
    if (!evals) return [];
    return Object.entries(evals);
  }, [evals]);

  useEffect(() => {
    if (!selected && sortedEvals.length > 0) {
      setSelected(sortedEvals[0][0]);
    }
  }, [sortedEvals, selected]);

  const currentEval = selected ? evals?.[selected] : null;

  // Chart data for comparing all sensors
  const chartData = useMemo(() => {
    return sortedEvals.map(([name, ev]) => ({
      name: prettyName(name).slice(0, 12) + (name.length > 12 ? ".." : ""),
      fullName: prettyName(name),
      sensor: name,
      MAPE: Math.round(ev.mape * 100) / 100,
      sMAPE: Math.round(ev.smape * 100) / 100,
      "Q-Loss": Math.round(ev.q_loss * 1000) / 1000,
      status: ev.status,
    }));
  }, [sortedEvals]);

  // Helper to get metric threshold status
  const getMetricStatus = (metric: "mape" | "smape" | "qloss", val: number) => {
    if (metric === "qloss") {
      if (val < 0.05) return { label: "GOOD", color: "text-good bg-good/10 border-good/30", barColor: "#2d7a3c", desc: "The confidence intervals are highly calibrated and accurate." };
      if (val < 0.15) return { label: "BETTER (OPTIMAL)", color: "text-warn bg-warn/10 border-warn/30", barColor: "#c2742c", desc: "The intervals are reliable, capturing future fluctuations well." };
      return { label: "BAD (POOR)", color: "text-crit bg-crit/10 border-crit/40", barColor: "#b13a1e", desc: "The confidence intervals are under-estimating or over-estimating future risk." };
    } else {
      // MAPE or sMAPE
      if (val < 2.0) return { label: "GOOD", color: "text-good bg-good/10 border-good/30", barColor: "#2d7a3c", desc: "Superb forecasting accuracy with less than 2% average error." };
      if (val < 5.0) return { label: "BETTER (OPTIMAL)", color: "text-warn bg-warn/10 border-warn/30", barColor: "#c2742c", desc: "Highly acceptable forecasting accuracy for industrial environments." };
      return { label: "BAD (POOR)", color: "text-crit bg-crit/10 border-crit/40", barColor: "#b13a1e", desc: "Significant deviation from actual values. Requires model recalibration." };
    }
  };

  return (
    <div className="card p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <ShieldCheck size={18} className="text-good" />
          <div>
            <h3 className="font-semibold text-sm text-ink">Chronos Model Evaluation</h3>
            <p className="text-[10px] text-muted">Continuous backtesting on recent sensor history</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {loading && <RefreshCw size={12} className="animate-spin text-muted" />}
          <span className="text-[10px] bg-ink/5 border border-ink/10 px-2 py-0.5 rounded text-muted font-mono">
            Updated every 10s
          </span>
        </div>
      </div>

      {err && <div className="mb-4 text-xs text-crit bg-crit/10 p-2 rounded border border-crit/20">{err}</div>}

      {!evals ? (
        <div className="h-[240px] flex flex-col items-center justify-center text-center p-4">
          <RefreshCw size={24} className="animate-spin text-muted mb-2" />
          <p className="text-xs text-muted">Computing model evaluation metrics...</p>
          <p className="text-[10px] text-muted/70 mt-1 max-w-[280px]">
            Chronos is backtesting predictions against recent InfluxDB history. This takes about 15 seconds.
          </p>
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-3">
          {/* List & Selection */}
          <div className="lg:col-span-1 border-r border-ink/10 pr-2 max-h-[350px] overflow-y-auto">
            <span className="text-[10px] uppercase tracking-wider text-muted font-bold block mb-2">
              Sensor Accuracy list
            </span>
            <div className="space-y-1">
              {sortedEvals.map(([name, ev]) => {
                const isSelected = selected === name;
                const statusColor =
                  ev.status === "good"
                    ? "bg-good"
                    : ev.status === "better"
                    ? "bg-warn"
                    : "bg-crit";
                return (
                  <button
                    key={name}
                    onClick={() => setSelected(name)}
                    className={clsx(
                      "w-full text-left px-2.5 py-2 rounded-lg text-xs transition flex items-center justify-between border",
                      isSelected
                        ? "bg-ink/5 border-ink/20 font-semibold text-ink"
                        : "border-transparent hover:bg-ink/5/40 text-muted"
                    )}
                  >
                    <span className="truncate pr-2">{prettyName(name)}</span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="font-mono text-[10px] opacity-80">{ev.mape.toFixed(1)}%</span>
                      <span className={clsx("w-2 h-2 rounded-full", statusColor)} />
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Details & Metrics Breakdown */}
          <div className="lg:col-span-2 space-y-4">
            {currentEval && (
              <div>
                <div className="flex items-center justify-between border-b border-ink/10 pb-2 mb-3">
                  <h4 className="font-bold text-sm text-ink">{prettyName(currentEval.sensor)} Metrics</h4>
                  <span
                    className={clsx(
                      "text-[10px] font-bold px-2 py-0.5 rounded-full border tracking-wider",
                      currentEval.status === "good"
                        ? "text-good border-good/40 bg-good/10"
                        : currentEval.status === "better"
                        ? "text-warn border-warn/45 bg-warn/10"
                        : "text-crit border-crit/40 bg-crit/10"
                    )}
                  >
                    OVERALL: {currentEval.status.toUpperCase()}
                  </span>
                </div>

                <div className="space-y-3">
                  {/* MAPE */}
                  <MetricProgressBar
                    label="MAPE (Mean Absolute Percentage Error)"
                    value={currentEval.mape}
                    unit="%"
                    statusInfo={getMetricStatus("mape", currentEval.mape)}
                    max={10}
                  />

                  {/* sMAPE */}
                  <MetricProgressBar
                    label="sMAPE (Symmetric Mean Absolute Percentage Error)"
                    value={currentEval.smape}
                    unit="%"
                    statusInfo={getMetricStatus("smape", currentEval.smape)}
                    max={10}
                  />

                  {/* Q-Loss */}
                  <MetricProgressBar
                    label="Q-Loss (Scaled Quantile Loss)"
                    value={currentEval.q_loss}
                    unit=""
                    statusInfo={getMetricStatus("qloss", currentEval.q_loss)}
                    max={0.3}
                  />
                </div>

                {/* Explanation Box */}
                <div className="mt-4 bg-ink/5 p-3 rounded-xl border border-ink/10 text-xs">
                  <div className="flex items-center gap-1.5 font-bold text-ink mb-1">
                    <Info size={12} className="text-muted" />
                    How to read these metrics:
                  </div>
                  <ul className="list-disc pl-4 space-y-1 text-muted text-[11px] leading-relaxed">
                    <li>
                      <strong className="text-ink">MAPE / sMAPE</strong> measure forecast drift. A value below{" "}
                      <span className="text-good font-bold">2.0%</span> is excellent (<span className="text-good">Good</span>), below{" "}
                      <span className="text-warn font-bold">5.0%</span> is optimal (<span className="text-warn">Better</span>), and above is{" "}
                      <span className="text-crit font-bold">Poor</span>.
                    </li>
                    <li>
                      <strong className="text-ink">Q-Loss</strong> evaluates the reliability of the shaded 90% confidence band.
                      A lower score means the band perfectly covers the actual values without being too wide.
                    </li>
                  </ul>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Bar Chart comparing all sensors */}
      {chartData.length > 0 && (
        <div className="mt-5 border-t border-ink/10 pt-4">
          <span className="text-[10px] uppercase tracking-wider text-muted font-bold block mb-2">
            MAPE Comparison across all sensors
          </span>
          <div className="h-[180px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#d8c9ad" />
                <XAxis dataKey="name" tick={{ fontSize: 9, fill: "#8a7355" }} />
                <YAxis tick={{ fontSize: 9, fill: "#8a7355" }} />
                <Tooltip
                  contentStyle={{
                    background: "#fffbf5",
                    border: "1px solid #cdb994",
                    borderRadius: 8,
                    fontSize: 11,
                  }}
                  formatter={(value: any, name: any, props: any) => [
                    `${value}%`,
                    `${name} (${props.payload.status.toUpperCase()})`,
                  ]}
                />
                <Bar
                  dataKey="MAPE"
                  fill="#8a4a1f"
                  radius={[4, 4, 0, 0]}
                  onClick={(data) => {
                    if (data && data.sensor) setSelected(data.sensor);
                  }}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}

interface MetricProgressProps {
  label: string;
  value: number;
  unit: string;
  max: number;
  statusInfo: {
    label: string;
    color: string;
    barColor: string;
    desc: string;
  };
}

function MetricProgressBar({ label, value, unit, max, statusInfo }: MetricProgressProps) {
  // Cap percentage for the bar display
  const fillPct = Math.min((value / max) * 100, 100);

  return (
    <div className="space-y-1">
      <div className="flex justify-between items-end">
        <span className="text-xs font-medium text-ink">{label}</span>
        <div className="flex items-center gap-1.5 text-xs">
          <span className="font-mono font-bold text-ink">
            {value.toFixed(3)}
            {unit}
          </span>
          <span className={clsx("text-[9px] font-bold px-1.5 py-0.5 rounded border uppercase", statusInfo.color)}>
            {statusInfo.label}
          </span>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="h-2 bg-ink/5 rounded-full overflow-hidden border border-ink/10 relative">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: `${fillPct}%`,
            backgroundColor: statusInfo.barColor,
          }}
        />
      </div>
      <p className="text-[10px] text-muted leading-tight">{statusInfo.desc}</p>
    </div>
  );
}
