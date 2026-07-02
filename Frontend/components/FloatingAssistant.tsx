"use client";
import { useEffect, useState } from "react";
import { ChatPanel } from "./ChatPanel";
import { Bot, X, Sparkles } from "lucide-react";
import clsx from "clsx";

export function FloatingAssistant() {
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(true);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const toggle = () => {
    setOpen((v) => !v);
    setUnread(false);
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className={clsx(
          "fixed inset-0 bg-[#2a1d10]/30 backdrop-blur-sm z-30 transition-opacity",
          open ? "opacity-100" : "opacity-0 pointer-events-none",
        )}
        onClick={() => setOpen(false)}
      />

      {/* Slide-in panel */}
      <aside
        className={clsx(
          "fixed top-0 right-0 h-full z-40 transition-transform duration-300 ease-out",
          "w-full sm:w-[440px] lg:w-[520px]",
          open ? "translate-x-0" : "translate-x-full",
        )}
        aria-hidden={!open}
      >
        <div className="h-full flex flex-col bg-card border-l border-border shadow-2xl shadow-black/50">
          <div className="px-5 py-4 border-b border-border flex items-center justify-between bg-gradient-to-r from-accent/10 to-accent2/10">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl grid place-items-center gradient-accent shadow-lg shadow-accent/30">
                <Sparkles size={16} className="text-white" />
              </div>
              <div>
                <div className="font-bold text-sm">Boiler Assistant</div>
                <div className="text-[11px] text-muted flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-good animate-pulse" />
                  Online · agentic RAG
                </div>
              </div>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="w-8 h-8 rounded-lg grid place-items-center text-muted hover:text-ink hover:bg-white/5 transition"
              aria-label="Close assistant"
            >
              <X size={18} />
            </button>
          </div>

          <div className="flex-1 min-h-0">
            {open && <ChatPanel />}
          </div>
        </div>
      </aside>

      {/* Floating action button */}
      <button
        onClick={toggle}
        className={clsx(
          "fixed bottom-6 right-6 z-50 group",
          "transition-all duration-300",
          open && "scale-0 opacity-0 pointer-events-none",
        )}
        aria-label="Open assistant"
      >
        <span className="absolute inset-0 rounded-full gradient-accent blur-xl opacity-60 group-hover:opacity-100 transition" />
        <span className="relative w-16 h-16 rounded-full gradient-accent shadow-2xl shadow-accent/40 grid place-items-center text-white border border-white/10 group-hover:scale-110 transition">
          <Bot size={26} />
          {unread && (
            <span className="absolute top-1 right-1 w-3 h-3 rounded-full bg-crit ring-2 ring-bg animate-pulse" />
          )}
        </span>
        <span className="absolute right-full mr-3 top-1/2 -translate-y-1/2 whitespace-nowrap text-xs bg-card border border-border px-3 py-1.5 rounded-lg opacity-0 group-hover:opacity-100 transition shadow-lg">
          Ask Boiler-AI
        </span>
      </button>
    </>
  );
}
