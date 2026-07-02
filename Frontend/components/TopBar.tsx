"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchHealth } from "@/lib/api";
import { Flame } from "lucide-react";
import clsx from "clsx";

export function TopBar() {
  const [status, setStatus] = useState<"ok" | "err" | "wait">("wait");

  useEffect(() => {
    let stop = false;
    const ping = async () => {
      try {
        await fetchHealth();
        if (!stop) setStatus("ok");
      } catch {
        if (!stop) setStatus("err");
      }
    };
    ping();
    const id = setInterval(ping, 5000);
    return () => { stop = true; clearInterval(id); };
  }, []);

  const dotColor =
    status === "ok" ? "bg-good" : status === "err" ? "bg-crit" : "bg-warn";
  const label =
    status === "ok" ? "Live" : status === "err" ? "Offline" : "Connecting…";

  return (
    <header className="sticky top-0 z-20 backdrop-blur-xl bg-bg/60 border-b border-border/60">
      <div className="mx-auto max-w-7xl px-6 py-3 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-3 group">
          <div className="relative w-10 h-10 rounded-xl grid place-items-center gradient-accent shadow-lg shadow-accent/30 group-hover:scale-105 transition">
            <Flame size={20} className="text-white" />
            <span className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-good ring-2 ring-bg" />
          </div>
          <div>
            <div className="font-bold tracking-wide">BOILER-AI</div>
            <div className="text-xs text-muted">Realtime Industrial Monitoring</div>
          </div>
        </Link>

        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-panel/80 border border-border text-xs text-muted">
          <span className={clsx("w-2 h-2 rounded-full shadow-[0_0_8px_currentColor]", dotColor)} />
          {label}
        </div>
      </div>
    </header>
  );
}
