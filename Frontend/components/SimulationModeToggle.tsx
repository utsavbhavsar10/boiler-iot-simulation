"use client";
import { useState } from "react";
import { setSimulationMode, forceChronosRefresh } from "@/lib/api";
import { Zap, ToggleLeft, ToggleRight, Loader2 } from "lucide-react";
import clsx from "clsx";

interface Props {
  currentMode: "normal" | "degradation";
  onModeChange: (mode: "normal" | "degradation") => void;
}

export function SimulationModeToggle({ currentMode, onModeChange }: Props) {
  const [loading, setLoading] = useState(false);
  const [err, setErr]         = useState<string | null>(null);

  const toggle = async () => {
    const next = currentMode === "normal" ? "degradation" : "normal";
    setLoading(true);
    setErr(null);
    try {
      await setSimulationMode(next);
      onModeChange(next);
      // Silently trigger an immediate Chronos refresh so the forecast chart
      // picks up the new mode's history window within seconds, not 30s.
      forceChronosRefresh().catch(() => { /* non-critical — ignore */ });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const isDegradation = currentMode === "degradation";

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between gap-3">
        {/* Label */}
        <div>
          <div className="text-[11px] uppercase tracking-wide text-muted mb-0.5">
            Simulation Mode
          </div>
          <div className="flex items-center gap-2">
            <span
              className={clsx(
                "inline-flex items-center gap-1.5 font-bold text-sm tracking-wide",
                isDegradation ? "text-crit" : "text-good",
              )}
            >
              {isDegradation ? (
                <>
                  <Zap size={14} className="animate-pulse" />
                  DEGRADATION
                </>
              ) : (
                <>
                  <span className="w-2 h-2 rounded-full bg-good animate-pulse" />
                  NORMAL
                </>
              )}
            </span>
          </div>
          {isDegradation && (
            <div className="text-[11px] text-crit/80 mt-0.5 font-mono">
              Thermal drift active → main_steam_temp ↑
            </div>
          )}
          {err && (
            <div className="text-[11px] text-crit mt-0.5">{err}</div>
          )}
        </div>

        {/* Toggle button */}
        <button
          onClick={toggle}
          disabled={loading}
          className={clsx(
            "relative shrink-0 flex items-center gap-2 px-4 py-2 rounded-xl border font-semibold text-xs transition-all duration-200",
            isDegradation
              ? "border-crit/50 bg-crit/10 text-crit hover:bg-crit/20"
              : "border-warn/50 bg-warn/10 text-warn hover:bg-warn/20",
            loading && "opacity-60 cursor-wait",
          )}
          title={`Switch to ${isDegradation ? "Normal" : "Degradation"} mode`}
        >
          {loading ? (
            <Loader2 size={14} className="animate-spin" />
          ) : isDegradation ? (
            <ToggleRight size={14} />
          ) : (
            <ToggleLeft size={14} />
          )}
          {isDegradation ? "→ Normal" : "→ Degrade"}
        </button>
      </div>

      {/* Mode description strip */}
      <div className="mt-3 text-[11px] text-muted leading-relaxed">
        {isDegradation
          ? "⚠ Chronos alert pipeline is active. Breaching critical will trigger auto-recovery."
          : "Boiler sensors oscillate within normal operating bounds. Safe/Warning phase cycling."}
      </div>
    </div>
  );
}
