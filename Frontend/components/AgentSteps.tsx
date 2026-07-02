"use client";
import clsx from "clsx";
import { Wrench, CheckCircle2, Loader2, Database, Activity, History, TrendingUp, Brain } from "lucide-react";

export interface StepState {
  step: number;
  tool: string;
  args: Record<string, unknown>;
  state: "running" | "done";
  resultPreview?: string;
  resultLength?: number;
}

const TOOL_META: Record<string, { label: string; icon: React.ReactNode }> = {
  fetch_realtime_sensors: { label: "Fetching realtime sensors",          icon: <Activity   size={11} /> },
  search_knowledge_base:  { label: "Searching knowledge base",            icon: <Database   size={11} /> },
  get_fault_history:      { label: "Loading fault history",              icon: <History    size={11} /> },
  predict_trend:          { label: "Predicting trend (Chronos AI)",      icon: <TrendingUp size={11} /> },
  get_chronos_forecast:   { label: "Chronos probabilistic forecast",     icon: <Brain      size={11} /> },
};

export function AgentSteps({ steps }: { steps: StepState[] }) {
  return (
    <div className="mb-3 rounded-xl border border-accent/20 bg-accent/5 p-3 text-xs space-y-2">
      <div className="text-[10px] uppercase tracking-wider text-muted font-semibold flex items-center gap-1.5">
        <Wrench size={11} /> Agent Reasoning
      </div>
      {steps.map((s, i) => {
        const meta = TOOL_META[s.tool] ?? { label: s.tool, icon: <Wrench size={11} /> };
        const running = s.state === "running";
        return (
          <div key={i} className="flex items-start gap-2">
            <div className={clsx(
              "w-5 h-5 rounded-full grid place-items-center shrink-0 mt-0.5",
              running ? "bg-accent text-white animate-pulse-ring" : "bg-good text-white",
            )}>
              {running ? <Loader2 size={10} className="animate-spin" /> : <CheckCircle2 size={10} />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 font-mono text-[11px] text-ink">
                {meta.icon}
                <span>{meta.label}</span>
                {running && <DotsInline />}
              </div>
              {Object.keys(s.args).length > 0 && (
                <div className="text-[10px] text-muted font-mono mt-0.5 truncate">
                  args: {JSON.stringify(s.args)}
                </div>
              )}
              {!running && s.resultLength != null && (
                <div className="text-[10px] text-good mt-0.5">
                  ✓ received {s.resultLength} chars
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DotsInline() {
  return (
    <span className="inline-flex gap-0.5">
      <span className="w-1 h-1 rounded-full bg-accent animate-bounce-dot" />
      <span className="w-1 h-1 rounded-full bg-accent animate-bounce-dot" style={{ animationDelay: "0.15s" }} />
      <span className="w-1 h-1 rounded-full bg-accent animate-bounce-dot" style={{ animationDelay: "0.3s" }} />
    </span>
  );
}
