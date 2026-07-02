"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchStatus,
  fetchChronosHealth,
  fetchRedisHealth,
  fetchMetrics,
  StatusResponse,
  ChronosHealthResponse,
  RedisHealthResponse,
  MetricsResponse,
} from "@/lib/api";
import {
  BOILER_SENSORS, CHIMNEY_SENSORS, classify,
} from "@/lib/sensors";
import { SensorCard } from "./SensorCard";
import { TrendChart } from "./TrendChart";
import { FaultsList } from "./FaultsList";
import { SimulationModeToggle } from "./SimulationModeToggle";
import { ChronosForecastChart } from "./ChronosForecastChart";
import { ChronosEvaluationChart } from "./ChronosEvaluationChart";
import { AlertTriangle, CheckCircle2, Cpu, Clock, Brain, Zap, Database, Activity } from "lucide-react";

const REFRESH_MS = 3000;
const CHRONOS_REFRESH_MS = 30_000; // matches server-side cache refresh
const HISTORY_POINTS = 30;

interface HistoryPoint {
  t: string;
  [k: string]: number | string;
}

export function Dashboard() {
  const [status,        setStatus]        = useState<StatusResponse | null>(null);
  const [chronosHealth, setChronosHealth] = useState<ChronosHealthResponse | null>(null);
  const [redisHealth,   setRedisHealth]   = useState<RedisHealthResponse | null>(null);
  const [metrics,       setMetrics]       = useState<MetricsResponse | null>(null);
  const [err,           setErr]           = useState<string | null>(null);
  const [history,       setHistory]       = useState<HistoryPoint[]>([]);
  const lastFetch = useRef<number>(0);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const s = await fetchStatus();
        if (!alive) return;
        setStatus(s);
        setErr(null);
        lastFetch.current = Date.now();

        const t = new Date().toLocaleTimeString();
        const point: HistoryPoint = { t };
        for (const k of [
          "main_steam_pressure_boiler", "main_steam_temp_boiler",
          "co", "co2", "o2", "flue_temp",
        ]) {
          const v = s.sensors?.[k]?.value;
          if (typeof v === "number") point[k] = v;
        }
        setHistory((h) => [...h, point].slice(-HISTORY_POINTS));
      } catch (e) {
        if (alive) setErr((e as Error).message);
      }
    };
    tick();
    const id = setInterval(tick, REFRESH_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  // Chronos health — poll every 30s (matches server cache interval)
  useEffect(() => {
    let alive = true;
    const pollChronos = async () => {
      try {
        const ch = await fetchChronosHealth();
        if (alive) setChronosHealth(ch);
      } catch { /* silently fail — Chronos optional */ }
    };
    pollChronos();
    const id = setInterval(pollChronos, CHRONOS_REFRESH_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  // Poll Redis and Metrics every 15s
  useEffect(() => {
    let alive = true;
    const pollStats = async () => {
      try {
        const rh = await fetchRedisHealth();
        if (alive) setRedisHealth(rh);
      } catch { /* ignore offline */ }

      try {
        const m = await fetchMetrics();
        if (alive) setMetrics(m);
      } catch { /* ignore offline */ }
    };
    pollStats();
    const id = setInterval(pollStats, 15_000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  // Listen for Chronos auto-recovery event broadcast by AlertBanner.
  // When fired, immediately flip the simulation mode toggle to NORMAL
  // without waiting for the next /status/json poll (up to 3s lag).
  useEffect(() => {
    const handleAutoRecovery = () => {
      setStatus((prev) => prev ? { ...prev, simulation_mode: "normal" } : null);
    };
    window.addEventListener("chronos:autorecovery", handleAutoRecovery);
    return () => window.removeEventListener("chronos:autorecovery", handleAutoRecovery);
  }, []);

  const summary = useMemo(() => {
    if (!status) return null;
    const tallyFor = (group: readonly string[]) => {
      let crit = 0, warn = 0, total = 0;
      for (const k of group) {
        const v = status.sensors?.[k]?.value;
        if (v == null) continue;
        total++;
        const s = classify(k, v);
        if (s === "crit") crit++;
        else if (s === "warn") warn++;
      }
      const label = crit > 0 ? "CRITICAL" : warn > 0 ? "WARNING" : total > 0 ? "NORMAL" : "—";
      const color = crit > 0 ? "text-crit" : warn > 0 ? "text-warn" : total > 0 ? "text-good" : "text-muted";
      return { crit, warn, total, label, color };
    };
    return {
      boiler: tallyFor(BOILER_SENSORS),
      chimney: tallyFor(CHIMNEY_SENSORS),
    };
  }, [status]);

  const faults = Array.isArray(status?.faults) ? (status!.faults as any[]) : [];

  return (
    <div className="space-y-6 animate-fade-in">
      {err && (
        <div className="card p-4 border-crit/60 bg-crit/10 text-crit text-sm">
          API error: {err} — make sure FastAPI is running on the configured base URL.
        </div>
      )}

      {/* Controls & Engine Health */}
      <SectionHeader title="🎛️ System Controls & Engine Health" />
      <div className="grid gap-4 grid-cols-1 md:grid-cols-3">
        <SimulationModeToggle
          currentMode={(status?.simulation_mode as any) || "normal"}
          onModeChange={(m) => setStatus((prev) => prev ? { ...prev, simulation_mode: m } : null)}
        />
        <RedisHealthCard redis={redisHealth} />
        <AIPerformanceCard metrics={metrics} />
      </div>

      {/* Row 1: Status summary cards */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <SummaryCard
          label="Boiler"
          value={summary?.boiler.label ?? "—"}
          meta={summary ? `${summary.boiler.total} sensors · ${summary.boiler.warn}W / ${summary.boiler.crit}C` : "awaiting data"}
          color={summary?.boiler.color}
          icon={<Cpu />}
        />
        <SummaryCard
          label="Chimney"
          value={summary?.chimney.label ?? "—"}
          meta={summary ? `${summary.chimney.total} sensors · ${summary.chimney.warn}W / ${summary.chimney.crit}C` : "awaiting data"}
          color={summary?.chimney.color}
          icon={<AlertTriangle />}
        />
        <SummaryCard
          label="Active Faults (60m)"
          value={String(faults.length)}
          meta={faults.length === 0 ? "no faults" : "see list below"}
          color={faults.length === 0 ? "text-good" : "text-warn"}
          icon={faults.length === 0 ? <CheckCircle2 /> : <AlertTriangle />}
        />
        <SummaryCard
          label="Last Update"
          value={status ? new Date(status.timestamp).toLocaleTimeString() : "—"}
          meta={`auto-refresh ${REFRESH_MS / 1000}s`}
          color="text-ink"
          icon={<Clock />}
        />
        {/* Chronos Forecast Status Card */}
        <ChronosCard chronos={chronosHealth} />
      </div>

      <SectionHeader title="🔥 Boiler Sensors" />
      <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {BOILER_SENSORS.map((s) => (
          <SensorCard
            key={s}
            name={s}
            value={status?.sensors?.[s]?.value}
            error={status?.sensors?.[s]?.error}
          />
        ))}
      </div>

      <SectionHeader title="🏭 Chimney Sensors" />
      <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {CHIMNEY_SENSORS.map((s) => (
          <SensorCard
            key={s}
            name={s}
            value={status?.sensors?.[s]?.value}
            error={status?.sensors?.[s]?.error}
          />
        ))}
      </div>

      <SectionHeader title="🧠 Chronos AI · Future Predictions" />
      <div className="grid gap-4 md:grid-cols-1">
        <ChronosForecastChart simulationMode={(status?.simulation_mode as "normal" | "degradation") ?? "normal"} />
        <ChronosEvaluationChart />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card p-5">
          <div className="font-semibold mb-3 text-sm">Steam Pressure & Temp (Boiler)</div>
          <TrendChart
            data={history}
            series={[
              { key: "main_steam_pressure_boiler", color: "#8a4a1f", label: "Pressure (MPa)", yAxisId: "left" },
              { key: "main_steam_temp_boiler", color: "#d49019", label: "Temp (°C)", yAxisId: "right" },
            ]}
            twoAxis
          />
        </div>
        <div className="card p-5">
          <div className="font-semibold mb-3 text-sm">Chimney Emissions (CO · CO₂ · O₂)</div>
          <TrendChart
            data={history}
            series={[
              { key: "co", color: "#b13a1e", label: "CO (ppm)" },
              { key: "co2", color: "#c2742c", label: "CO₂ (%)" },
              { key: "o2", color: "#6b8a3a", label: "O₂ (%)" },
            ]}
          />
        </div>
      </div>

      <div className="card p-5">
        <div className="font-semibold mb-3 text-sm">Recent Faults (last 60 minutes)</div>
        <FaultsList faults={faults} />
      </div>
    </div>
  );
}

function SectionHeader({ title }: { title: string }) {
  return (
    <div className="text-xs font-semibold uppercase tracking-widest text-muted mt-2">
      {title}
    </div>
  );
}

function SummaryCard({
  label, value, meta, color, icon,
}: { label: string; value: string; meta: string; color?: string; icon: React.ReactNode }) {
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
        <div className="text-muted">{icon}</div>
      </div>
      <div className={clsxJoin("text-2xl font-bold mt-1.5", color ?? "text-ink")}>{value}</div>
      <div className="text-xs text-muted mt-1">{meta}</div>
    </div>
  );
}

function ChronosCard({ chronos }: { chronos: ChronosHealthResponse | null }) {
  if (!chronos) {
    return (
      <SummaryCard
        label="Chronos AI Forecast"
        value="Awaiting Data"
        meta="No response yet"
        color="text-muted"
        icon={<Brain className="opacity-50" />}
      />
    );
  }

  let statusText = "Offline";
  let color = "text-muted";
  if (chronos.status === "healthy") {
    statusText = "Healthy";
    color = "text-good";
  } else if (chronos.status === "warming_up") {
    statusText = "Warming Up";
    color = "text-warn";
  } else if (chronos.status === "stale") {
    statusText = "Stale";
    color = "text-crit";
  }

  const meta = `${chronos.sensors_forecasted}/${chronos.sensors_total} forecasted · ${chronos.sensors_with_warnings}W / ${chronos.sensors_with_critical}C`;

  return (
    <SummaryCard
      label="Chronos AI Forecast"
      value={statusText}
      meta={meta}
      color={color}
      icon={<Brain className={chronos.status === "healthy" ? "animate-pulse" : ""} />}
    />
  );
}

function clsxJoin(...x: (string | undefined)[]) { return x.filter(Boolean).join(" "); }

function RedisHealthCard({ redis }: { redis: RedisHealthResponse | null }) {
  if (!redis) {
    return (
      <div className="card p-4 flex flex-col justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-muted mb-0.5">
            Redis Chat Cache
          </div>
          <div className="font-bold text-sm tracking-wide text-muted font-mono">AWAITING DATA</div>
        </div>
        <div className="text-[11px] text-muted mt-3">Connecting to Redis cache...</div>
      </div>
    );
  }

  const isUp = redis.status === "up";
  return (
    <div className="card p-4 flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11px] uppercase tracking-wide text-muted">
            Redis Chat Cache
          </div>
          <div className="text-muted"><Database size={14} /></div>
        </div>
        <div className="flex items-center gap-2 mt-1">
          <span
            className={clsxJoin(
              "inline-flex items-center gap-1.5 font-bold text-sm tracking-wide",
              isUp ? "text-good" : "text-crit"
            )}
          >
            {isUp ? (
              <>
                <span className="w-2 h-2 rounded-full bg-good animate-pulse" />
                ONLINE
              </>
            ) : (
              "OFFLINE"
            )}
          </span>
        </div>
      </div>
      <div className="mt-3 text-[11px] text-muted leading-relaxed">
        {isUp ? (
          <>
            <div>Active Sessions: <span className="font-semibold text-ink">{redis.active_sessions ?? 0}</span></div>
            <div className="mt-0.5">Memory: <span className="font-mono text-ink">{redis.used_memory_human ?? "0B"}</span> / {redis.maxmemory_human ?? "unlimited"}</div>
          </>
        ) : (
          <span className="text-crit/80">{redis.message || "Redis connection failed. Chat history disabled."}</span>
        )}
      </div>
    </div>
  );
}

function AIPerformanceCard({ metrics }: { metrics: MetricsResponse | null }) {
  if (!metrics || !metrics.averages_24h || Object.keys(metrics.averages_24h).length === 0) {
    return (
      <div className="card p-4 flex flex-col justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-muted mb-0.5">
            AI Agent Quality (24h)
          </div>
          <div className="font-bold text-sm tracking-wide text-muted font-mono">NO EVAL DATA</div>
        </div>
        <div className="text-[11px] text-muted mt-3">Ask questions to generate RAGAS scores.</div>
      </div>
    );
  }

  const avgs = metrics.averages_24h;
  const overall = avgs.overall_quality;
  const qualityPct = overall != null ? Math.round(overall * 100) : null;

  return (
    <div className="card p-4 flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11px] uppercase tracking-wide text-muted">
            AI Agent Quality (24h)
          </div>
          <div className="text-muted"><Activity size={14} /></div>
        </div>
        <div className="flex items-baseline gap-1.5 mt-1">
          <span className="text-xl font-extrabold text-ink">
            {qualityPct != null ? `${qualityPct}%` : "—"}
          </span>
          <span className="text-[10px] text-muted font-medium">Overall Quality</span>
        </div>
      </div>
      <div className="mt-3 text-[11px] text-muted grid grid-cols-2 gap-x-2 gap-y-1">
        <div>Faithfulness: <span className="font-semibold text-ink">{avgs.faithfulness != null ? `${Math.round(avgs.faithfulness * 100)}%` : "—"}</span></div>
        <div>Relevancy: <span className="font-semibold text-ink">{avgs.answer_relevancy != null ? `${Math.round(avgs.answer_relevancy * 100)}%` : "—"}</span></div>
        <div>Tool Precision: <span className="font-semibold text-ink">{avgs.tool_precision != null ? `${Math.round(avgs.tool_precision * 100)}%` : "—"}</span></div>
        <div>Latency: <span className="font-semibold text-ink">{avgs.latency_ms != null ? `${(avgs.latency_ms / 1000).toFixed(1)}s` : "—"}</span></div>
      </div>
    </div>
  );
}
