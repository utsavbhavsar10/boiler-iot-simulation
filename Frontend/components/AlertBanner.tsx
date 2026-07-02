"use client";
import { useEffect, useRef, useState } from "react";
import { connectAlertSocket, type ChronosAlert, type AffectedSensor } from "@/lib/api";
import { AlertTriangle, ShieldCheck, RotateCcw, X, AlertCircle } from "lucide-react";
import clsx from "clsx";

type Tier = "WARNING" | "CRITICAL";

// Static Tailwind class maps — keep literal strings so JIT compiles them.
const PALETTE = {
  red: {
    h2: "text-red-200", h3: "text-red-300", h4: "text-red-400",
    h1: "text-red-100", h2soft: "text-red-200/80", h3soft: "text-red-300/80",
    h2soft2: "text-red-200/70", h4soft: "text-red-400/70",
    border: "border-red-800/50",
  },
  amber: {
    h2: "text-amber-200", h3: "text-amber-300", h4: "text-amber-400",
    h1: "text-amber-100", h2soft: "text-amber-200/80", h3soft: "text-amber-300/80",
    h2soft2: "text-amber-200/70", h4soft: "text-amber-400/70",
    border: "border-amber-800/50",
  },
  green: {
    h2: "text-green-200", h3: "text-green-300", h4: "text-green-400",
    h1: "text-green-100", h2soft: "text-green-200/80", h3soft: "text-green-300/80",
    h2soft2: "text-green-200/70", h4soft: "text-green-400/70",
    border: "border-green-800/50",
  },
} as const;
type Accent = keyof typeof PALETTE;

export function AlertBanner() {
  const [alert, setAlert]         = useState<ChronosAlert | null>(null);
  const [recovered, setRecovered] = useState(false);
  const [visible, setVisible]     = useState(false);
  const cleanupRef   = useRef<(() => void) | null>(null);
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const recoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const connect = () => {
      cleanupRef.current?.();
      cleanupRef.current = connectAlertSocket(
        (data) => {
          if (data.type === "heartbeat") return;
          setAlert(data);
          setRecovered(false);
          setVisible(true);

          if (dismissTimer.current) clearTimeout(dismissTimer.current);
          if (recoverTimer.current) clearTimeout(recoverTimer.current);

          if (data.auto_recovery) {
            // CRITICAL: dispatch event immediately so Dashboard flips toggle
            // to NORMAL without waiting for the 3-second poll cycle.
            window.dispatchEvent(new CustomEvent("chronos:autorecovery"));
            // Show recovery state after 4s, dismiss after 30s
            recoverTimer.current = setTimeout(() => setRecovered(true), 4_000);
            dismissTimer.current = setTimeout(() => setVisible(false), 30_000);
          } else {
            // WARNING: auto-dismiss after 20s (operator can still see/act)
            dismissTimer.current = setTimeout(() => setVisible(false), 20_000);
          }
        },
        () => {
          setTimeout(connect, 3_000);
        },
      );
    };

    connect();
    return () => {
      cleanupRef.current?.();
      if (dismissTimer.current) clearTimeout(dismissTimer.current);
      if (recoverTimer.current) clearTimeout(recoverTimer.current);
    };
  }, []);

  if (!visible || !alert) return null;

  const tier: Tier = (alert.severity as Tier) ?? "CRITICAL";
  const affected: AffectedSensor[] = alert.affected_sensors ?? [];

  // Style per tier
  const isCritical = tier === "CRITICAL";
  const containerCls = recovered
    ? "bg-green-950/90 border-green-700/60 text-green-100"
    : isCritical
      ? "bg-red-950/90 border-red-700/60 text-red-100"
      : "bg-amber-950/90 border-amber-700/60 text-amber-100";

  const iconBgCls = recovered
    ? "bg-green-700/40"
    : isCritical
      ? "bg-red-700/40"
      : "bg-amber-700/40";

  const accent: Accent = recovered ? "green" : isCritical ? "red" : "amber";

  return (
    <div className="fixed top-16 left-1/2 -translate-x-1/2 z-50 w-full max-w-3xl px-4 animate-slide-down">
      <div className={clsx("rounded-2xl border px-5 py-4 shadow-2xl flex items-start gap-4 backdrop-blur-sm", containerCls)}>
        {/* Icon */}
        <div className={clsx("w-10 h-10 rounded-xl grid place-items-center shrink-0 mt-0.5", iconBgCls)}>
          {recovered ? (
            <ShieldCheck size={20} className="text-green-300" />
          ) : isCritical ? (
            <AlertTriangle size={20} className="text-red-300 animate-pulse" />
          ) : (
            <AlertCircle size={20} className="text-amber-300 animate-pulse" />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {recovered ? (
            <RecoveredBlock />
          ) : (
            <>
              <Header alert={alert} tier={tier} accent={accent} />
              <Summary alert={alert} tier={tier} accent={accent} />
              {affected.length > 0 && (
                <FailureDetail affected={affected} tier={tier} accent={accent} />
              )}
            </>
          )}
          <div className="text-[11px] text-current/50 mt-2">
            {new Date(alert.timestamp).toLocaleTimeString()}
          </div>
        </div>

        {/* Dismiss */}
        <button
          onClick={() => setVisible(false)}
          className="shrink-0 w-7 h-7 rounded-lg grid place-items-center text-current/50 hover:text-current hover:bg-white/10 transition mt-0.5"
          aria-label="Dismiss alert"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}

function RecoveredBlock() {
  return (
    <>
      <div className="font-bold text-sm tracking-wide text-green-200">
        ✅ AUTO-RECOVERY SUCCESSFUL
      </div>
      <div className="text-sm text-green-300 mt-0.5">
        Simulation mode reset to{" "}
        <span className="font-semibold text-green-100">NORMAL</span>. System stabilised.
      </div>
    </>
  );
}

function Header({ alert, tier, accent }: { alert: ChronosAlert; tier: Tier; accent: Accent }) {
  const isCrit = tier === "CRITICAL";
  const p = PALETTE[accent];
  return (
    <div className={clsx("font-bold text-sm tracking-wide flex items-center gap-2", p.h2)}>
      {isCrit ? "🚨 CHRONOS CRITICAL FORECAST" : "⚠️ CHRONOS WARNING FORECAST"}
      {alert.auto_recovery && (
        <span className="inline-flex items-center gap-1 text-[11px] bg-amber-700/40 text-amber-200 border border-amber-600/40 rounded-full px-2 py-0.5 font-semibold">
          <RotateCcw size={10} className="animate-spin" />
          Auto-Recovery Active
        </span>
      )}
    </div>
  );
}

function Summary({ alert, tier, accent }: { alert: ChronosAlert; tier: Tier; accent: Accent }) {
  const isCrit = tier === "CRITICAL";
  const minutes = isCrit ? alert.minutes_to_critical : alert.minutes_to_warning;
  const breachWord = isCrit ? "CRITICAL" : "WARNING";
  const p = PALETTE[accent];

  // Format ETA: never show "0.0 min" — use "IMMINENT" for very small values.
  const etaLabel =
    minutes == null
      ? "—"
      : minutes <= 0.15
      ? "IMMINENT (< 1 min)"
      : `${minutes.toFixed(1)} min`;

  return (
    <div className={clsx("text-sm mt-0.5", p.h3)}>
      <span className={clsx("font-mono font-semibold", p.h1)}>
        {alert.sensor?.replace(/_/g, " ")}
      </span>{" "}
      will breach {breachWord} threshold in{" "}
      <span className={clsx("font-bold", p.h1)}>
        {etaLabel}
      </span>
      {alert.anomaly_score != null && (
        <span className={clsx("ml-2 text-[11px]", p.h4)}>
          · anomaly {(alert.anomaly_score * 100).toFixed(0)}%
        </span>
      )}
      {alert.forecast_value != null && (
        <span className={clsx("ml-2 text-[11px]", p.h4)}>
          · forecast {alert.forecast_value.toFixed(1)}
        </span>
      )}
      {alert.cause && (
        <div className={clsx("mt-1 text-[12px] italic", p.h2soft)}>
          {alert.cause}
        </div>
      )}
    </div>
  );
}

function FailureDetail({
  affected, tier, accent,
}: { affected: AffectedSensor[]; tier: Tier; accent: Accent }) {
  const p = PALETTE[accent];
  return (
    <div className={clsx("mt-3 rounded-lg border p-2.5 bg-black/20", p.border)}>
      <div className={clsx("text-[10px] uppercase tracking-widest font-semibold mb-1.5", p.h3soft)}>
        Affected sensors ({affected.length})
      </div>
      <div className="space-y-1.5 max-h-44 overflow-y-auto pr-1">
        {affected.map((a) => {
          const eta = tier === "CRITICAL" ? a.minutes_to_critical : a.minutes_to_warning;
          const lo  = tier === "CRITICAL" ? a.crit_low  : a.warn_low;
          const hi  = tier === "CRITICAL" ? a.crit_high : a.warn_high;
          // Format ETA similarly: no "0.0 min"
          const etaStr =
            eta == null
              ? null
              : eta <= 0.15
              ? "IMMINENT"
              : `${eta.toFixed(1)} min`;
          return (
            <div key={a.sensor} className="text-[12px] leading-snug">
              <div className="flex items-center justify-between gap-2">
                <span className={clsx("font-mono font-semibold", p.h1)}>
                  {a.sensor.replace(/_/g, " ")}
                </span>
                <span className={clsx("text-[11px] font-mono", p.h3)}>
                  {a.current ?? "—"}{" "}
                  <span className={p.h4soft}>
                    (band {lo ?? "—"} – {hi ?? "—"})
                  </span>
                  {etaStr != null && (
                    <span className={clsx("ml-2", p.h2)}>· {etaStr}</span>
                  )}
                </span>
              </div>
              <div className={clsx("text-[11px]", p.h2soft2)}>{a.cause}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
