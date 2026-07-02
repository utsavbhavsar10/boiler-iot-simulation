"use client";
import clsx from "clsx";

interface Fault {
  code?: string;
  sensor?: string;
  severity?: string;
  timestamp?: string;
  value?: number;
  [k: string]: unknown;
}

export function FaultsList({ faults }: { faults: Fault[] }) {
  if (!faults || faults.length === 0) {
    return <div className="text-sm text-muted">No faults detected in the last 60 minutes. ✅</div>;
  }
  return (
    <div className="flex flex-col gap-2 max-h-72 overflow-y-auto pr-1">
      {faults.map((f, i) => {
        const sev = (f.severity ?? "").toUpperCase();
        const isCrit = sev === "CRITICAL";
        return (
          <div
            key={i}
            className={clsx(
              "flex justify-between items-center px-3 py-2 rounded bg-panel border-l-4",
              isCrit ? "border-crit" : "border-warn",
            )}
          >
            <div>
              <div className="font-mono font-semibold text-sm">{f.code ?? "FAULT"}</div>
              <div className="text-xs text-muted">
                {f.sensor ?? "—"} {f.value != null ? `· ${f.value}` : ""}
              </div>
            </div>
            <div className="text-right">
              <div className={clsx("text-xs font-bold", isCrit ? "text-crit" : "text-warn")}>{sev || "WARN"}</div>
              <div className="text-[11px] text-muted">
                {f.timestamp ? new Date(f.timestamp).toLocaleTimeString() : ""}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
