"use client";
import clsx from "clsx";
import {
  SENSOR_UNITS, SENSOR_NORMAL, classify, prettyName, pctInRange,
} from "@/lib/sensors";

export function SensorCard({
  name, value, error,
}: { name: string; value?: number | null; error?: string }) {
  const sev = classify(name, value);
  const unit = SENSOR_UNITS[name] ?? "";
  const range = SENSOR_NORMAL[name];
  const pct = pctInRange(name, value);

  const borderClass =
    sev === "crit" ? "border-crit/70 bg-crit/10"
    : sev === "warn" ? "border-warn/60"
    : "border-border";
  const badge = {
    good: "bg-good/15 text-good",
    warn: "bg-warn/15 text-warn",
    crit: "bg-crit/20 text-crit",
    unknown: "bg-muted/15 text-muted",
  }[sev];
  const fill = {
    good: "bg-accent", warn: "bg-warn", crit: "bg-crit", unknown: "bg-muted",
  }[sev];

  return (
    <div className={clsx(
      "card p-4 relative overflow-hidden transition hover:-translate-y-0.5",
      borderClass,
    )}>
      <span className={clsx(
        "absolute top-2.5 right-2.5 text-[10px] font-bold tracking-wide px-2 py-0.5 rounded-full",
        badge,
      )}>
        {sev.toUpperCase()}
      </span>
      <div className="text-[11px] text-muted uppercase tracking-wide">{prettyName(name)}</div>
      <div className="mt-1.5 font-mono text-2xl font-semibold">
        {error ? <span className="text-crit text-sm">ERR</span>
          : value == null ? <span className="text-muted text-sm">no data</span>
          : value.toFixed(2)}
        <span className="ml-1 text-sm text-muted font-sans">{unit}</span>
      </div>
      {range && (
        <div className="mt-1 text-[11px] text-muted">
          normal {range[0]} – {range[1]} {unit}
        </div>
      )}
      <div className="mt-2.5 h-1 rounded bg-ink/10 overflow-hidden">
        <div className={clsx("h-full transition-all duration-500", fill)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
