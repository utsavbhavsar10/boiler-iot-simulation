"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, ReferenceLine, ReferenceArea,
} from "recharts";
import {
  fetchChronosForecast, ChronosForecastResponse, SensorForecast,
  fetchStatus, StatusResponse,
} from "@/lib/api";
import { SENSOR_NORMAL, SENSOR_CRITICAL, SENSOR_UNITS, prettyName } from "@/lib/sensors";
import {
  Brain, AlertTriangle, AlertCircle, CheckCircle2,
  Zap, RefreshCw, TrendingUp, TrendingDown, Minus,
  Info, Shield, ShieldAlert, ShieldX,
} from "lucide-react";
import clsx from "clsx";

const REFRESH_MS        = 8_000;
const MODE_CHANGE_MS    = 6_000;
const GRID_COLOR        = "#d8c9ad";
const AXIS_COLOR        = "#8a7355";

type State = SensorForecast["state"];

// ── Risk % calculator ───────────────────────────────────────────────────────
// Returns 0–100: how far the value is inside the danger zone.
// 0 = comfortably normal, 100 = at or beyond critical threshold.
function calcRiskPct(sensor: string, value: number): number {
  const norm = SENSOR_NORMAL[sensor];
  const crit = SENSOR_CRITICAL[sensor];
  if (!norm || !crit) return 0;

  const LOW_SIDE = new Set(["oxygen_level", "o2", "condenser_vacuum", "draft"]);
  const isLow = LOW_SIDE.has(sensor);

  if (isLow) {
    // Risk increases as value drops below normal low
    const normalLow = norm[0];
    const critLow   = crit[0];
    if (value >= normalLow) return 0;                      // normal — no risk
    if (value <= critLow)   return 100;                    // at/beyond critical
    return Math.round(((normalLow - value) / (normalLow - critLow)) * 100);
  } else {
    // Risk increases as value rises above normal high
    const normalHigh = norm[1];
    const critHigh   = crit[1];
    if (value <= normalHigh) return 0;
    if (value >= critHigh)   return 100;
    return Math.round(((value - normalHigh) / (critHigh - normalHigh)) * 100);
  }
}

function getRiskLabel(pct: number): { label: string; color: string; bg: string } {
  if (pct === 0)  return { label: "No Risk",       color: "#2d7a3c", bg: "#dcfce7" };
  if (pct < 30)   return { label: "Low Risk",      color: "#4a7c20", bg: "#ecfccb" };
  if (pct < 60)   return { label: "Medium Risk",   color: "#c2742c", bg: "#fef3c7" };
  if (pct < 85)   return { label: "High Risk",     color: "#d45a1e", bg: "#fee2e2" };
  return           { label: "Critical Risk",  color: "#b13a1e", bg: "#fecaca" };
}

// ── Trend detector ───────────────────────────────────────────────────────────
function detectTrend(values: number[]): "rising" | "falling" | "stable" {
  if (values.length < 3) return "stable";
  const first = values.slice(0, Math.ceil(values.length / 3)).reduce((a, b) => a + b, 0) / Math.ceil(values.length / 3);
  const last  = values.slice(-Math.ceil(values.length / 3)).reduce((a, b) => a + b, 0) / Math.ceil(values.length / 3);
  const pct   = Math.abs((last - first) / (first || 1)) * 100;
  if (pct < 1.5) return "stable";
  return last > first ? "rising" : "falling";
}

// ── Chart data point ─────────────────────────────────────────────────────────
interface ChartPoint {
  step:        string;
  timeMin:     number;          // minutes from NOW (0 = NOW)
  median?:     number;          // Chronos median forecast
  bandLow?:    number;          // P10 lower bound
  bandHigh?:   number;          // P90 upper bound
  worstCase?:  number;          // worst-case projection
  actual?:     number;          // live NOW value (step 0 only)
  riskPct?:    number;          // 0–100 risk at this point
}

interface Props {
  simulationMode?: "normal" | "degradation";
}

// ── Custom Tooltip ───────────────────────────────────────────────────────────
function ChronosTooltip({
  active, payload, label, sensor, unit, thresholds,
}: {
  active?: boolean;
  payload?: any[];
  label?: string;
  sensor: string;
  unit: string;
  thresholds: { norm?: [number, number]; crit?: [number, number] } | null;
}) {
  if (!active || !payload?.length) return null;

  const point: ChartPoint = payload[0]?.payload ?? {};
  const isNow = label === "NOW";

  // Pull values from payload
  const median    = payload.find((p) => p.dataKey === "median")?.value;
  const worstCase = payload.find((p) => p.dataKey === "worstCase")?.value;
  const bandLow   = point.bandLow;
  const bandHigh  = point.bandHigh;
  const actual    = point.actual;
  const riskPct   = point.riskPct ?? (median != null ? calcRiskPct(sensor, median) : 0);
  const riskInfo  = getRiskLabel(riskPct);

  // Distance from warning threshold
  let distanceNote = "";
  if (thresholds?.norm && median != null) {
    const [nLo, nHi] = thresholds.norm;
    if (median > nHi)      distanceNote = `+${(median - nHi).toFixed(2)} ${unit} above warning`;
    else if (median < nLo) distanceNote = `${(median - nLo).toFixed(2)} ${unit} below warning`;
    else {
      const nearLo = Math.abs(median - nLo);
      const nearHi = Math.abs(median - nHi);
      const nearest = nearLo < nearHi ? nLo : nHi;
      distanceNote = `${Math.abs(median - nearest).toFixed(2)} ${unit} from warning`;
    }
  }

  return (
    <div style={{
      background: "#fffbf5",
      border: "1.5px solid #cdb994",
      borderRadius: 12,
      padding: "10px 14px",
      fontSize: 12,
      color: "#3b2c1c",
      boxShadow: "0 8px 32px rgba(80,50,20,0.18)",
      minWidth: 200,
      maxWidth: 260,
    }}>
      {/* Time label */}
      <div style={{ color: "#8a7355", fontWeight: 700, fontSize: 11, marginBottom: 6, letterSpacing: "0.06em" }}>
        {isNow ? "⚡ RIGHT NOW (Live Sensor)" : `⏱ ${label} from now — Chronos Forecast`}
      </div>

      {/* Actual live value */}
      {actual != null && (
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
          <span style={{ color: "#8a7355" }}>Live Sensor</span>
          <span style={{ fontWeight: 700, fontFamily: "monospace", color: "#2d7a3c" }}>
            {actual.toFixed(3)} {unit}
          </span>
        </div>
      )}

      {/* Chronos median — only shown for forecast steps */}
      {!isNow && median != null && (
        <>
          <div style={{ borderTop: "1px dashed #e0c89a", margin: "6px 0" }} />
          <div style={{ fontSize: 10, color: "#8a7355", marginBottom: 4, fontStyle: "italic" }}>
            🤖 Chronos AI Prediction
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
            <span style={{ color: "#8a7355" }}>Predicted value</span>
            <span style={{ fontWeight: 700, fontFamily: "monospace", color: "#8a4a1f" }}>
              {median.toFixed(3)} {unit}
            </span>
          </div>

          {bandLow != null && bandHigh != null && (
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
              <span style={{ color: "#8a7355" }}>90% likely range</span>
              <span style={{ fontFamily: "monospace", color: "#a05c2a", fontSize: 11 }}>
                {bandLow.toFixed(2)} – {bandHigh.toFixed(2)}
              </span>
            </div>
          )}

          {worstCase != null && (
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
              <span style={{ color: "#8a7355" }}>Worst-case scenario</span>
              <span style={{ fontFamily: "monospace", color: "#b13a1e", fontSize: 11, fontWeight: 700 }}>
                {worstCase.toFixed(3)} {unit}
              </span>
            </div>
          )}

          {/* Risk % bar */}
          <div style={{ borderTop: "1px dashed #e0c89a", margin: "6px 0" }} />
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
            <span style={{ color: "#8a7355" }}>Risk level</span>
            <span style={{
              fontWeight: 700, fontSize: 11,
              padding: "1px 7px", borderRadius: 999,
              background: riskInfo.bg, color: riskInfo.color,
            }}>
              {riskInfo.label} ({riskPct}%)
            </span>
          </div>
          {/* Risk bar */}
          <div style={{ background: "#e8d8bc", borderRadius: 99, height: 5, marginBottom: 4 }}>
            <div style={{
              width: `${riskPct}%`, height: "100%", borderRadius: 99,
              background: riskPct < 30 ? "#2d7a3c" : riskPct < 60 ? "#c2742c" : "#b13a1e",
              transition: "width 0.3s",
            }} />
          </div>

          {distanceNote && (
            <div style={{ fontSize: 10, color: "#8a7355", fontStyle: "italic" }}>{distanceNote}</div>
          )}
        </>
      )}
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────
export function ChronosForecastChart({ simulationMode }: Props) {
  const [resp, setResp]         = useState<ChronosForecastResponse | null>(null);
  const [liveStatus, setLive]   = useState<StatusResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [err, setErr]           = useState<string | null>(null);
  const [modeChanging, setModeChanging] = useState(false);

  const prevModeRef  = useRef<string | undefined>(simulationMode);
  const modeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Fetch forecast ──────────────────────────────────────────────────────────
  const fetchForecast = useCallback(async () => {
    try {
      const r = await fetchChronosForecast();
      if ("forecasts" in r) { setResp(r); setErr(null); }
    } catch (e) { setErr((e as Error).message); }
  }, []);

  useEffect(() => {
    let alive = true;
    const tick = async () => { if (!alive) return; await fetchForecast(); };
    tick();
    const id = setInterval(tick, REFRESH_MS);
    return () => { alive = false; clearInterval(id); };
  }, [fetchForecast]);

  // React to mode changes immediately
  useEffect(() => {
    if (simulationMode === undefined) return;
    if (prevModeRef.current === simulationMode) return;
    prevModeRef.current = simulationMode;
    setModeChanging(true);
    if (modeTimerRef.current) clearTimeout(modeTimerRef.current);
    modeTimerRef.current = setTimeout(() => setModeChanging(false), MODE_CHANGE_MS);
    let count = 0;
    const id = setInterval(async () => {
      await fetchForecast(); count++;
      if (count >= 3) clearInterval(id);
    }, 2_000);
    fetchForecast();
    return () => clearInterval(id);
  }, [simulationMode, fetchForecast]);

  useEffect(() => () => { if (modeTimerRef.current) clearTimeout(modeTimerRef.current); }, []);

  // ── Live sensor poll ────────────────────────────────────────────────────────
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try { const s = await fetchStatus(); if (alive) setLive(s); } catch { /**/ }
    };
    poll();
    const id = setInterval(poll, 3_000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  // ── Sorted sensors ──────────────────────────────────────────────────────────
  const sorted = useMemo<[string, SensorForecast][]>(() => {
    if (!resp?.forecasts) return [];
    return Object.entries(resp.forecasts);
  }, [resp]);

  useEffect(() => {
    if (!selected && sorted.length > 0) setSelected(sorted[0][0]);
  }, [sorted, selected]);

  const current: SensorForecast | null =
    (selected && resp?.forecasts?.[selected]) || sorted[0]?.[1] || null;

  // ── Live value ──────────────────────────────────────────────────────────────
  const liveValue: number | null = useMemo(() => {
    if (!current || !liveStatus?.sensors) return null;
    return liveStatus.sensors[current.sensor]?.value ?? null;
  }, [current, liveStatus]);

  // ── Effective state with live-value override ────────────────────────────────
  const effectiveState: State = useMemo(() => {
    if (!current) return "normal";
    if (resp?.mode === "normal" && liveValue != null) {
      const norm = SENSOR_NORMAL[current.sensor];
      if (norm && liveValue >= norm[0] && liveValue <= norm[1]) return "normal";
    }
    return current.state;
  }, [current, resp, liveValue]);

  // ── Stale detection ─────────────────────────────────────────────────────────
  const isStale: boolean = useMemo(() => {
    if (liveValue == null || !current?.forecast_values?.length) return false;
    const first = current.forecast_values[0];
    if (first === 0) return false;
    return Math.abs((liveValue - first) / first) > 0.05;
  }, [liveValue, current]);

  // ── Build chart points ──────────────────────────────────────────────────────
  const data: ChartPoint[] = useMemo(() => {
    if (!current) return [];
    const fv     = current.forecast_values ?? [];
    const lo     = current.lower_bound ?? [];
    const hi     = current.upper_bound ?? [];
    const stepSec = current.horizon_seconds && fv.length
      ? Math.round(current.horizon_seconds / fv.length) : 30;
    const LOW_SIDE = new Set(["oxygen_level", "o2", "condenser_vacuum", "draft"]);
    const isLow = LOW_SIDE.has(current.sensor);

    const nowPoint: ChartPoint | null = liveValue != null ? {
      step: "NOW", timeMin: 0,
      actual: Math.round(liveValue * 100) / 100,
      riskPct: calcRiskPct(current.sensor, liveValue),
    } : null;

    const forecastPoints: ChartPoint[] = fv.map((v, i) => {
      const loV = lo[i] ?? v;
      const hiV = hi[i] ?? v;
      const worst = isLow ? Math.min(v, loV) : Math.max(v, hiV);
      const timeMin = Math.round(((i + 1) * stepSec) / 60 * 10) / 10;
      return {
        step:      `+${timeMin}m`,
        timeMin,
        median:    Math.round(v   * 100) / 100,
        bandLow:   Math.round(loV * 100) / 100,
        bandHigh:  Math.round(hiV * 100) / 100,
        worstCase: Math.round(worst * 100) / 100,
        riskPct:   calcRiskPct(current.sensor, worst),
      };
    });

    return nowPoint ? [nowPoint, ...forecastPoints] : forecastPoints;
  }, [current, liveValue]);

  // ── Thresholds ──────────────────────────────────────────────────────────────
  const thresholds = useMemo(() => {
    if (!current) return null;
    return {
      norm: SENSOR_NORMAL[current.sensor] as [number, number] | undefined,
      crit: SENSOR_CRITICAL[current.sensor] as [number, number] | undefined,
    };
  }, [current]);

  // ── Trend detection ─────────────────────────────────────────────────────────
  const trend = useMemo(() => {
    if (!current?.forecast_values?.length) return "stable";
    return detectTrend(current.forecast_values);
  }, [current]);

  // ── Peak risk in forecast window ────────────────────────────────────────────
  const peakRisk = useMemo(() => {
    const pts = data.filter((d) => d.riskPct != null && d.step !== "NOW");
    if (!pts.length) return 0;
    return Math.max(...pts.map((d) => d.riskPct!));
  }, [data]);

  // ── Summary stats ───────────────────────────────────────────────────────────
  const summary = useMemo(() => {
    if (!resp?.forecasts) return { total: 0, normal: 0, warn: 0, crit: 0 };
    const vals = Object.values(resp.forecasts);
    return {
      total:  vals.length,
      normal: vals.filter((f) => f.state === "normal").length,
      warn:   vals.filter((f) => f.state === "warning_approaching").length,
      crit:   vals.filter((f) =>
        f.state === "critical_approaching" || f.state === "critical"
      ).length,
    };
  }, [resp]);

  // ── Y-axis domain — auto with padding ──────────────────────────────────────
  const yDomain = useMemo((): [number | string, number | string] => {
    if (!data.length || !thresholds?.crit) return ["auto", "auto"];
    const allVals = data.flatMap((d) => [
      d.actual, d.median, d.bandLow, d.bandHigh, d.worstCase,
    ]).filter((v): v is number => v != null);
    if (!allVals.length) return ["auto", "auto"];
    const pad = (thresholds.crit[1] - thresholds.crit[0]) * 0.1;
    return [
      Math.min(...allVals, thresholds.crit[0]) - pad,
      Math.max(...allVals, thresholds.crit[1]) + pad,
    ];
  }, [data, thresholds]);

  const unit        = SENSOR_UNITS[current?.sensor ?? ""] ?? "";
  const horizonMin  = Math.round((current?.horizon_seconds ?? 0) / 60);
  const peakRiskInfo = getRiskLabel(peakRisk);
  const liveRisk    = liveValue != null && current
    ? calcRiskPct(current.sensor, liveValue) : 0;
  const liveRiskInfo = getRiskLabel(liveRisk);

  return (
    <div className="card p-5">

      {/* ── Header ── */}
      <div className="flex items-start justify-between gap-3 flex-wrap mb-3">
        <div className="flex items-center gap-2 flex-wrap">
          <Brain size={16} className="text-muted" />
          <div className="font-semibold text-sm">Chronos AI · Future Prediction</div>
          {resp?.mode && (
            <span className={clsx(
              "text-[10px] uppercase tracking-widest font-bold px-2 py-0.5 rounded-full border",
              resp.mode === "degradation"
                ? "text-crit border-crit/40 bg-crit/10"
                : "text-good border-good/40 bg-good/10",
            )}>
              {resp.mode}
            </span>
          )}
          {modeChanging && (
            <span className="inline-flex items-center gap-1 text-[10px] text-muted animate-pulse">
              <RefreshCw size={10} className="animate-spin" />
              Refreshing…
            </span>
          )}
        </div>
        {/* Fleet pills */}
        <div className="flex items-center gap-1.5 text-[11px]">
          <FleetPill icon={<Shield size={10} />} label="Normal" value={summary.normal} cls="text-good bg-good/10 border-good/30" />
          <FleetPill icon={<ShieldAlert size={10} />} label="Warning" value={summary.warn} cls="text-warn bg-warn/10 border-warn/30" />
          <FleetPill icon={<ShieldX size={10} />} label="Critical" value={summary.crit} cls="text-crit bg-crit/10 border-crit/40" />
        </div>
      </div>

      {err && <div className="mb-2 text-[12px] text-crit">Forecast unavailable: {err}</div>}

      {/* ── Sensor selector tabs ── */}
      {sorted.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {sorted.slice(0, 8).map(([name, fc]) => {
            const displayState = name === current?.sensor ? effectiveState : fc.state;
            const isSel = name === current?.sensor;
            const stateColors: Record<State, string> = {
              normal:               "text-good bg-good/10 border-good/30",
              warning_approaching:  "text-warn bg-warn/10 border-warn/30",
              critical_approaching: "text-crit bg-crit/15 border-crit/40",
              critical:             "text-crit bg-crit/20 border-crit/60",
            };
            return (
              <button
                key={name}
                onClick={() => setSelected(name)}
                title={`${prettyName(name)} — click to view forecast`}
                className={clsx(
                  "text-[11px] font-medium px-2.5 py-1 rounded-lg border transition-all",
                  stateColors[displayState],
                  isSel ? "ring-2 ring-offset-1 ring-ink/25 font-bold shadow-sm" : "opacity-75 hover:opacity-100",
                )}
              >
                {prettyName(name)}
              </button>
            );
          })}
        </div>
      )}

      {/* ── Stale banner ── */}
      {isStale && current && liveValue != null && (
        <div className="flex items-center gap-2 mb-2 px-3 py-2 rounded-lg bg-crit/10 border border-crit/40 text-crit text-[12px] font-medium">
          <Zap size={13} className="shrink-0 animate-pulse" />
          <span>
            <strong>Forecast is slightly stale.</strong>{" "}
            Live sensor reads <strong>{liveValue.toFixed(2)} {unit}</strong>,
            but Chronos last saw <strong>{current.forecast_values?.[0]?.toFixed(2) ?? "?"}</strong>.
            Refreshing in ~15s — predictions remain directionally valid.
          </span>
        </div>
      )}
      {modeChanging && !isStale && (
        <div className="flex items-center gap-2 mb-2 px-3 py-2 rounded-lg bg-ink/5 border border-ink/15 text-muted text-[12px]">
          <RefreshCw size={12} className="animate-spin shrink-0" />
          <span>Chronos is computing fresh forecast for <strong className="text-ink">{resp?.mode ?? simulationMode}</strong> mode. Chart will update shortly.</span>
        </div>
      )}

      {/* ── Selected sensor info bar ── */}
      {current && (
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 mb-3 px-3 py-2 rounded-xl bg-ink/5 border border-ink/10">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-muted">Selected Sensor</div>
            <div className="text-sm font-bold text-ink">
              {prettyName(current.sensor)}{" "}
              <span className="text-muted font-normal text-[11px]">({unit})</span>
            </div>
          </div>

          <StateBadge state={effectiveState} />

          {/* Live value + live risk */}
          {liveValue != null && (
            <div className="flex items-center gap-2">
              <div className="text-center">
                <div className="text-[10px] text-muted uppercase tracking-wide">Live Now</div>
                <div className="font-mono font-bold text-[13px] text-ink">
                  {liveValue.toFixed(2)} {unit}
                </div>
              </div>
              <div className="text-center">
                <div className="text-[10px] text-muted uppercase tracking-wide">Current Risk</div>
                <div
                  className="font-bold text-[12px] px-1.5 py-0.5 rounded-md"
                  style={{ color: liveRiskInfo.color, background: liveRiskInfo.bg }}
                >
                  {liveRisk}% — {liveRiskInfo.label}
                </div>
              </div>
            </div>
          )}

          {/* Trend arrow */}
          <div className="text-center">
            <div className="text-[10px] text-muted uppercase tracking-wide">Forecast Trend</div>
            <div className={clsx("flex items-center gap-1 font-semibold text-[12px]",
              trend === "rising" ? "text-crit" : trend === "falling" ? "text-good" : "text-muted"
            )}>
              {trend === "rising" ? <TrendingUp size={14} /> : trend === "falling" ? <TrendingDown size={14} /> : <Minus size={14} />}
              {trend === "rising" ? "Rising ↑" : trend === "falling" ? "Falling ↓" : "Stable →"}
            </div>
          </div>

          {/* Horizon */}
          <div className="text-center">
            <div className="text-[10px] text-muted uppercase tracking-wide">Prediction Window</div>
            <div className="font-semibold text-[12px] text-ink">~{horizonMin} min ahead</div>
          </div>

          {/* Anomaly score */}
          <div className="text-center">
            <div className="text-[10px] text-muted uppercase tracking-wide">Anomaly Score</div>
            <div className={clsx("font-bold text-[12px]",
              current.anomaly_score > 0.7 ? "text-crit" : current.anomaly_score > 0.4 ? "text-warn" : "text-good"
            )}>
              {(current.anomaly_score * 100).toFixed(0)}%
            </div>
          </div>

          {/* ETA badges */}
          {effectiveState !== "normal" && current.minutes_to_warning != null && (
            <div className="text-center">
              <div className="text-[10px] text-warn uppercase tracking-wide">Warning ETA</div>
              <div className="font-bold text-[12px] text-warn">
                {current.minutes_to_warning <= 0.15 ? "IMMINENT" : `${current.minutes_to_warning.toFixed(1)} min`}
              </div>
            </div>
          )}
          {effectiveState !== "normal" && current.minutes_to_critical != null && (
            <div className="text-center">
              <div className="text-[10px] text-crit uppercase tracking-wide">Critical ETA</div>
              <div className="font-bold text-[12px] text-crit animate-pulse">
                {current.minutes_to_critical <= 0.15 ? "IMMINENT!" : `${current.minutes_to_critical.toFixed(1)} min`}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Chart ── */}
      <div className="h-[300px] relative">
        {data.length === 0 ? (
          <div className="h-full grid place-items-center text-muted text-sm">
            {err ? "Forecast unavailable." : "Awaiting Chronos forecast…"}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 8, right: 50, left: 2, bottom: 4 }}>
              <defs>
                {/* Confidence band fill — warm amber */}
                <linearGradient id="bandFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor="#d49019" stopOpacity={0.30} />
                  <stop offset="100%" stopColor="#d49019" stopOpacity={0.04} />
                </linearGradient>
                {/* Warning zone fill */}
                <linearGradient id="warnZone" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor="#c2742c" stopOpacity={0.12} />
                  <stop offset="100%" stopColor="#c2742c" stopOpacity={0.04} />
                </linearGradient>
                {/* Critical zone fill */}
                <linearGradient id="critZone" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor="#b13a1e" stopOpacity={0.14} />
                  <stop offset="100%" stopColor="#b13a1e" stopOpacity={0.04} />
                </linearGradient>
              </defs>

              <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
              <XAxis
                dataKey="step"
                stroke={AXIS_COLOR}
                tick={{ fontSize: 10, fill: AXIS_COLOR }}
                tickLine={false}
                label={{
                  value: "← Actual Now   |   Chronos AI Prediction →",
                  position: "insideBottom", offset: -2,
                  fill: AXIS_COLOR, fontSize: 10, fontStyle: "italic",
                }}
              />
              <YAxis
                stroke={AXIS_COLOR}
                tick={{ fontSize: 10, fill: AXIS_COLOR }}
                tickLine={false}
                domain={yDomain}
                width={48}
                tickFormatter={(v) => v.toFixed(1)}
              />

              <Tooltip
                content={(props) => (
                  <ChronosTooltip
                    {...props}
                    sensor={current?.sensor ?? ""}
                    unit={unit}
                    thresholds={thresholds}
                  />
                )}
                cursor={{ stroke: "#8a7355", strokeWidth: 1.5, strokeDasharray: "4 2" }}
              />

              {/* ── Zone shading (background reference areas) ── */}
              {/* Warning zone — between norm high and crit high */}
              {thresholds?.norm && thresholds?.crit && (
                <>
                  <ReferenceArea
                    y1={thresholds.norm[1]} y2={thresholds.crit[1]}
                    fill="url(#warnZone)" fillOpacity={1}
                    label={{ value: "⚠ Warning Zone", position: "insideTopRight", fill: "#c2742c", fontSize: 9 }}
                  />
                  <ReferenceArea
                    y1={thresholds.crit[0]} y2={thresholds.norm[0]}
                    fill="url(#warnZone)" fillOpacity={1}
                    label={{ value: "⚠ Warning Zone", position: "insideBottomRight", fill: "#c2742c", fontSize: 9 }}
                  />
                  {/* Above critical threshold */}
                  <ReferenceArea
                    y1={thresholds.crit[1]} y2={yDomain[1] as number}
                    fill="url(#critZone)" fillOpacity={1}
                    label={{ value: "🚨 Critical", position: "insideTopRight", fill: "#b13a1e", fontSize: 9, fontWeight: 700 }}
                  />
                </>
              )}

              {/* ── Threshold lines ── */}
              {thresholds?.norm && (
                <>
                  <ReferenceLine y={thresholds.norm[1]}
                    stroke="#c2742c" strokeDasharray="5 4" strokeWidth={1.5}
                    label={{ value: `Warn ${thresholds.norm[1]}`, fill: "#c2742c", fontSize: 9, position: "right", fontWeight: 600 }}
                  />
                  <ReferenceLine y={thresholds.norm[0]}
                    stroke="#c2742c" strokeDasharray="5 4" strokeWidth={1.5}
                    label={{ value: `Warn ${thresholds.norm[0]}`, fill: "#c2742c", fontSize: 9, position: "right", fontWeight: 600 }}
                  />
                </>
              )}
              {thresholds?.crit && (
                <>
                  <ReferenceLine y={thresholds.crit[1]}
                    stroke="#b13a1e" strokeDasharray="2 4" strokeWidth={2}
                    label={{ value: `Crit ${thresholds.crit[1]}`, fill: "#b13a1e", fontSize: 9, position: "right", fontWeight: 700 }}
                  />
                  <ReferenceLine y={thresholds.crit[0]}
                    stroke="#b13a1e" strokeDasharray="2 4" strokeWidth={2}
                    label={{ value: `Crit ${thresholds.crit[0]}`, fill: "#b13a1e", fontSize: 9, position: "right", fontWeight: 700 }}
                  />
                </>
              )}

              {/* ── NOW divider line ── */}
              {data[0]?.step === "NOW" && (
                <ReferenceLine x="NOW"
                  stroke="#2d7a3c" strokeWidth={2} strokeDasharray="6 3"
                  label={{ value: "NOW", fill: "#2d7a3c", fontSize: 10, position: "top", fontWeight: 700 }}
                />
              )}

              {/* ── Confidence band (P10–P90) ── */}
              <Area
                type="monotone" dataKey="bandHigh" name="__bandHigh"
                stroke="none" fill="url(#bandFill)"
                isAnimationActive={false}
                legendType="none"
              />
              <Area
                type="monotone" dataKey="bandLow" name="__bandLow"
                stroke="none" fill="#f3eada"   // erase below bandLow
                isAnimationActive={false}
                legendType="none"
              />

              {/* ── Median forecast (main Chronos prediction line) ── */}
              <Line
                type="monotone" dataKey="median"
                name="Chronos Prediction"
                stroke="#8a4a1f" strokeWidth={2.5}
                dot={false}
                isAnimationActive={false}
                strokeOpacity={0.95}
              />

              {/* ── Worst-case risk line ── */}
              <Line
                type="monotone" dataKey="worstCase"
                name="Worst-case scenario"
                stroke="#b13a1e" strokeWidth={1.8}
                strokeDasharray="5 3"
                dot={false}
                isAnimationActive={false}
                strokeOpacity={0.80}
              />

              {/* ── Actual NOW dot (large, green) ── */}
              <Line
                type="monotone" dataKey="actual"
                name="Live Sensor (Right Now)"
                stroke={isStale ? "#b13a1e" : "#2d7a3c"}
                strokeWidth={0}
                dot={(props: any) => {
                  const { cx, cy, payload } = props;
                  if (payload?.actual == null) return <g key={props.key} />;
                  return (
                    <g key={props.key}>
                      {/* Pulse ring */}
                      <circle cx={cx} cy={cy} r={14}
                        fill={isStale ? "#b13a1e22" : "#2d7a3c22"}
                        className="animate-ping" style={{ transformOrigin: `${cx}px ${cy}px` }}
                      />
                      <circle cx={cx} cy={cy} r={8}
                        fill={isStale ? "#b13a1e" : "#2d7a3c"}
                        stroke="#fff" strokeWidth={2.5}
                      />
                    </g>
                  );
                }}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* ── Plain-English Legend ── */}
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 px-1">
        <LegendItem color="#2d7a3c" type="dot" label="Live sensor reading (right now)" />
        <LegendItem color="#8a4a1f" type="solid" label="Chronos AI predicted value" />
        <LegendItem color="#b13a1e" type="dashed" label="Worst-case scenario (upper risk bound)" />
        <LegendItem color="#d49019" type="band" label="90% confidence band (likely range)" />
        <LegendItem color="#c2742c" type="zone" label="Warning zone" />
        <LegendItem color="#b13a1e" type="zone" label="Critical zone" />
      </div>

      {/* ── Plain-English Insight Panel ── */}
      {current && data.length > 0 && (
        <InsightPanel
          sensor={current.sensor}
          unit={unit}
          liveValue={liveValue}
          liveRisk={liveRisk}
          peakRisk={peakRisk}
          peakRiskInfo={peakRiskInfo}
          trend={trend}
          effectiveState={effectiveState}
          horizonMin={horizonMin}
          minutesToWarning={current.minutes_to_warning}
          minutesToCritical={current.minutes_to_critical}
          forecastValues={current.forecast_values ?? []}
          thresholds={thresholds}
        />
      )}
    </div>
  );
}

// ── Plain-English Insight Panel ───────────────────────────────────────────────
function InsightPanel({
  sensor, unit, liveValue, liveRisk, peakRisk, peakRiskInfo,
  trend, effectiveState, horizonMin, minutesToWarning, minutesToCritical,
  forecastValues, thresholds,
}: {
  sensor: string; unit: string; liveValue: number | null;
  liveRisk: number; peakRisk: number; peakRiskInfo: ReturnType<typeof getRiskLabel>;
  trend: "rising" | "falling" | "stable";
  effectiveState: State; horizonMin: number;
  minutesToWarning: number | null | undefined;
  minutesToCritical: number | null | undefined;
  forecastValues: number[]; thresholds: { norm?: [number, number]; crit?: [number, number] } | null;
}) {
  const endValue   = forecastValues[forecastValues.length - 1];
  const startValue = forecastValues[0];
  const change     = endValue != null && startValue != null
    ? Math.abs(endValue - startValue).toFixed(2) : null;

  const trendDesc = trend === "rising"
    ? `rising by ~${change} ${unit} over the next ${horizonMin} min`
    : trend === "falling"
    ? `falling by ~${change} ${unit} over the next ${horizonMin} min`
    : `staying stable over the next ${horizonMin} min`;

  const stateIcons: Record<State, React.ReactNode> = {
    normal:               <CheckCircle2 size={14} className="text-good shrink-0" />,
    warning_approaching:  <AlertCircle  size={14} className="text-warn shrink-0" />,
    critical_approaching: <AlertTriangle size={14} className="text-crit shrink-0" />,
    critical:             <AlertTriangle size={14} className="text-crit shrink-0 animate-pulse" />,
  };

  const bgMap: Record<State, string> = {
    normal:               "bg-good/5 border-good/20",
    warning_approaching:  "bg-warn/8 border-warn/25",
    critical_approaching: "bg-crit/8 border-crit/30",
    critical:             "bg-crit/12 border-crit/40",
  };

  return (
    <div className={clsx("mt-3 rounded-xl border px-4 py-3 text-[12px]", bgMap[effectiveState])}>
      <div className="flex items-center gap-1.5 font-bold text-ink mb-2">
        <Info size={13} className="text-muted" />
        What does this graph tell you?
      </div>
      <div className="space-y-1.5 text-muted leading-relaxed">

        {/* Current state sentence */}
        <div className="flex items-start gap-1.5">
          {stateIcons[effectiveState]}
          <span>
            <strong className="text-ink">{prettyName(sensor)}</strong>{" "}
            {liveValue != null ? (
              <>is currently at <strong className="text-ink font-mono">{liveValue.toFixed(2)} {unit}</strong> — </>
            ) : ""}
            {effectiveState === "normal"
              ? "operating normally within safe limits."
              : effectiveState === "warning_approaching"
              ? "approaching the warning threshold. Monitor closely."
              : effectiveState === "critical_approaching"
              ? "approaching a critical level. Immediate attention needed."
              : "in a CRITICAL state. Take action now."}
          </span>
        </div>

        {/* Trend sentence */}
        <div className="flex items-start gap-1.5">
          <span className="mt-0.5 shrink-0">📈</span>
          <span>
            Chronos AI predicts this sensor will be{" "}
            <strong className="text-ink">{trendDesc}</strong>.
          </span>
        </div>

        {/* Risk sentence */}
        <div className="flex items-start gap-1.5">
          <span className="mt-0.5 shrink-0">⚡</span>
          <span>
            Peak forecast risk over the next {horizonMin} min:{" "}
            <strong style={{ color: peakRiskInfo.color }}>
              {peakRisk}% — {peakRiskInfo.label}
            </strong>.
            {peakRisk >= 60
              ? " Consider taking preventive action before this escalates."
              : peakRisk >= 30
              ? " Keep monitoring — risk is elevated."
              : " No immediate action needed."}
          </span>
        </div>

        {/* ETA sentences */}
        {minutesToWarning != null && effectiveState !== "normal" && (
          <div className="flex items-start gap-1.5">
            <span className="mt-0.5 shrink-0 text-warn">⚠️</span>
            <span>
              Chronos predicts it will reach the{" "}
              <strong className="text-warn">warning threshold</strong>{" "}
              in approximately{" "}
              <strong className="text-warn">
                {minutesToWarning <= 0.15 ? "under 30 seconds (IMMINENT)" : `${minutesToWarning.toFixed(1)} minutes`}
              </strong>.
            </span>
          </div>
        )}
        {minutesToCritical != null && effectiveState !== "normal" && (
          <div className="flex items-start gap-1.5">
            <span className="mt-0.5 shrink-0 text-crit">🚨</span>
            <span>
              <strong className="text-crit">Critical threshold</strong>{" "}
              could be reached in{" "}
              <strong className="text-crit">
                {minutesToCritical <= 0.15 ? "under 30 seconds (IMMINENT!)" : `${minutesToCritical.toFixed(1)} minutes`}
              </strong>{" "}
              — the red dashed line on the chart shows this worst-case path.
            </span>
          </div>
        )}

        {/* Confidence band explanation */}
        <div className="flex items-start gap-1.5 opacity-75">
          <span className="mt-0.5 shrink-0">📊</span>
          <span>
            The <strong className="text-ink">amber shaded area</strong> shows the 90% confidence band —
            Chronos is 90% confident the actual future value will stay within this range.
            The <strong className="text-ink">darker solid line</strong> is its single best prediction.
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────
const STATE_META: Record<State, { label: string; cls: string; Icon: any }> = {
  normal:               { label: "NORMAL",               cls: "text-good bg-good/10 border-good/30",  Icon: CheckCircle2 },
  warning_approaching:  { label: "WARNING APPROACHING",  cls: "text-warn bg-warn/10 border-warn/30",  Icon: AlertCircle },
  critical_approaching: { label: "CRITICAL APPROACHING", cls: "text-crit bg-crit/15 border-crit/40",  Icon: AlertTriangle },
  critical:             { label: "CRITICAL",             cls: "text-crit bg-crit/20 border-crit/60",  Icon: AlertTriangle },
};

function StateBadge({ state }: { state: State }) {
  const { label, cls, Icon } = STATE_META[state];
  return (
    <span className={clsx(
      "inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest px-2.5 py-1 rounded-lg border",
      cls,
    )}>
      <Icon size={11} />
      {label}
    </span>
  );
}

function FleetPill({ icon, label, value, cls }: { icon: React.ReactNode; label: string; value: number; cls: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 px-2 py-0.5 rounded-full border font-semibold", cls)}>
      {icon}
      <span className="font-mono">{value}</span>
      <span className="opacity-70">{label}</span>
    </span>
  );
}

function LegendItem({
  color, type, label,
}: {
  color: string;
  type: "dot" | "solid" | "dashed" | "band" | "zone";
  label: string;
}) {
  return (
    <div className="flex items-center gap-1.5 text-[11px] text-muted">
      {type === "dot" && (
        <div className="w-3 h-3 rounded-full border-2 border-white shadow" style={{ background: color }} />
      )}
      {type === "solid" && (
        <div className="w-6 h-0.5 rounded" style={{ background: color }} />
      )}
      {type === "dashed" && (
        <div className="w-6 h-0" style={{ borderTop: `2px dashed ${color}` }} />
      )}
      {type === "band" && (
        <div className="w-5 h-3 rounded" style={{ background: color, opacity: 0.35 }} />
      )}
      {type === "zone" && (
        <div className="w-5 h-3 rounded border" style={{ background: `${color}20`, borderColor: color }} />
      )}
      <span>{label}</span>
    </div>
  );
}
