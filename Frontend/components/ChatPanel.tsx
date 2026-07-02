"use client";
import { useEffect, useRef, useState } from "react";
import { streamChat, clearChatSession, fetchChatHistory, type AgentEvent } from "@/lib/api";
import { AgentSteps, type StepState } from "./AgentSteps";
import { Markdown } from "./Markdown";
import { Send, Trash2, User } from "lucide-react";
import clsx from "clsx";

interface Message {
  id: string;
  role: "user" | "bot";
  text: string;
  steps?: StepState[];
  status?: string;
  streaming?: boolean;
  latencyMs?: number;
}

const SUGGESTIONS = [
  "Is the boiler safe right now?",
  "Why is CO high and how do I fix it?",
  "Any recent faults in the last hour?",
  "Will flue gas temp breach soon?",
];

const WELCOME: Message = {
  id: "welcome",
  role: "bot",
  text:
    "**Hi! I'm Boiler-AI** 👋\n\nAsk me anything about your boiler, chimney, or turbine. I'll show each tool I call in realtime.",
};

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState<string>("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let sid = localStorage.getItem("boiler_chat_session_id");
    if (!sid) {
      sid = `session_${crypto.randomUUID()}`;
      localStorage.setItem("boiler_chat_session_id", sid);
    }
    setSessionId(sid);

    // Hydrate prior turns from Redis
    (async () => {
      try {
        const { messages: stored } = await fetchChatHistory(sid!);
        if (!stored?.length) return;
        const hydrated: Message[] = stored.map((m, i) => ({
          id: `hist_${i}_${m.timestamp}`,
          role: m.role === "user" ? "user" : "bot",
          text: m.content,
        }));
        setMessages([WELCOME, ...hydrated]);
      } catch (e) {
        console.warn("History hydrate failed:", e);
      }
    })();
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const send = async (question: string) => {
    if (!question.trim() || busy) return;
    setInput("");
    setBusy(true);

    const userMsg: Message = { id: crypto.randomUUID(), role: "user", text: question };
    const botId = crypto.randomUUID();
    const botMsg: Message = {
      id: botId, role: "bot", text: "",
      steps: [], status: "Analyzing your question", streaming: true,
    };
    setMessages((m) => [...m, userMsg, botMsg]);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    const update = (patch: Partial<Message>) =>
      setMessages((m) => m.map((x) => (x.id === botId ? { ...x, ...patch } : x)));

    const pushStep = (s: StepState) =>
      setMessages((m) => m.map((x) =>
        x.id === botId ? { ...x, steps: [...(x.steps ?? []), s] } : x,
      ));

    const updateLastStep = (patch: Partial<StepState>) =>
      setMessages((m) => m.map((x) => {
        if (x.id !== botId || !x.steps?.length) return x;
        const steps = [...x.steps];
        steps[steps.length - 1] = { ...steps[steps.length - 1], ...patch };
        return { ...x, steps };
      }));

    try {
      await streamChat(question, (evt: AgentEvent) => {
        switch (evt.type) {
          case "status":
            update({ status: evt.message });
            break;
          case "tool_start":
            pushStep({ step: evt.step, tool: evt.tool, args: evt.args, state: "running" });
            update({ status: `Calling ${evt.tool}` });
            break;
          case "tool_end":
            updateLastStep({
              state: "done",
              resultPreview: evt.result_preview,
              resultLength: evt.result_length,
            });
            update({ status: "Synthesizing answer" });
            break;
          case "answer_chunk":
            setMessages((m) => m.map((x) =>
              x.id === botId ? { ...x, text: x.text + evt.text, status: "Generating" } : x,
            ));
            break;
          case "done":
            update({
              streaming: false, status: undefined,
              latencyMs: evt.latency_ms,
              text: evt.answer || "(no answer)",
            });
            break;
          case "error":
            update({ streaming: false, status: undefined, text: `⚠️ ${evt.message}` });
            break;
        }
      }, ctrl.signal, sessionId || undefined);
    } catch (e) {
      update({
        streaming: false, status: undefined,
        text: `⚠️ Stream failed: ${(e as Error).message}`,
      });
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  };

  const clear = async () => {
    abortRef.current?.abort();
    if (sessionId) {
      try {
        await clearChatSession(sessionId);
      } catch (e) {
        console.error("Failed to clear chat session:", e);
      }
      const newSid = `session_${crypto.randomUUID()}`;
      localStorage.setItem("boiler_chat_session_id", newSid);
      setSessionId(newSid);
    }
    setMessages([WELCOME]);
  };

  return (
    <div className="flex flex-col h-full">
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-5 space-y-5">
        {messages.map((m) => (
          <MessageView key={m.id} msg={m} onSuggest={send} />
        ))}
      </div>

      <div className="px-4 pt-2 pb-1 flex justify-between items-center">
        <button
          onClick={clear}
          className="flex items-center gap-1.5 text-[11px] text-muted hover:text-ink transition"
        >
          <Trash2 size={11} /> Clear conversation
        </button>
        <span className="text-[10px] text-muted">↵ send · ⇧↵ newline</span>
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); send(input); }}
        className="p-3 border-t border-border bg-panel/50 flex gap-2 items-end"
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
          rows={1}
          placeholder="Ask Boiler-AI…"
          className="flex-1 resize-none bg-bg border border-border rounded-xl px-4 py-3 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/30 max-h-32 transition"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className={clsx(
            "gradient-accent text-white rounded-xl w-11 h-11 grid place-items-center shrink-0 shadow-lg shadow-accent/30 hover:scale-105 transition",
            (busy || !input.trim()) && "opacity-40 cursor-not-allowed hover:scale-100",
          )}
        >
          <Send size={16} />
        </button>
      </form>
    </div>
  );
}

function MessageView({
  msg, onSuggest,
}: { msg: Message; onSuggest: (q: string) => void }) {
  const isUser = msg.role === "user";
  return (
    <div className={clsx("flex gap-2.5 animate-fade-in", isUser && "flex-row-reverse")}>
      <div className={clsx(
        "w-7 h-7 rounded-lg grid place-items-center text-[10px] font-bold shrink-0 mt-0.5 shadow",
        isUser ? "bg-[#5a4528] text-ink" : "gradient-accent text-white",
      )}>
        {isUser ? <User size={13} /> : "AI"}
      </div>
      <div className={clsx("max-w-[88%] flex flex-col gap-1.5", isUser && "items-end")}>
        <div className={clsx(
          "rounded-2xl px-4 py-3 leading-relaxed border text-sm break-words",
          isUser
            ? "gradient-accent text-white border-transparent rounded-tr-sm"
            : "bg-panel border-border rounded-tl-sm",
        )}>
          {!isUser && msg.steps && msg.steps.length > 0 && <AgentSteps steps={msg.steps} />}
          {!isUser && msg.status && <StatusLine label={msg.status} />}
          {isUser ? (
            <div className="whitespace-pre-wrap">{msg.text}</div>
          ) : (
            <>
              <Markdown text={msg.text || ""} />
              {msg.streaming && !msg.status && <BlinkCursor />}
            </>
          )}
          {!isUser && msg.id === "welcome" && (
            <div className="flex flex-wrap gap-2 mt-3">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => onSuggest(s)}
                  className="text-[11px] bg-card border border-border hover:border-accent hover:text-accent rounded-full px-3 py-1.5 transition"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
        {!isUser && msg.latencyMs != null && (
          <div className="text-[10px] text-muted px-1">
            ⚡ {msg.latencyMs.toFixed(0)}ms · {msg.steps?.length ?? 0} tool{(msg.steps?.length ?? 0) === 1 ? "" : "s"}
          </div>
        )}
      </div>
    </div>
  );
}

function StatusLine({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted mb-2 italic">
      <span>{label}</span>
      <Dots />
    </div>
  );
}

function Dots() {
  return (
    <span className="inline-flex gap-1 ml-0.5">
      <span className="w-1.5 h-1.5 rounded-full bg-accent animate-bounce-dot" />
      <span className="w-1.5 h-1.5 rounded-full bg-accent animate-bounce-dot" style={{ animationDelay: "0.15s" }} />
      <span className="w-1.5 h-1.5 rounded-full bg-accent animate-bounce-dot" style={{ animationDelay: "0.3s" }} />
    </span>
  );
}

function BlinkCursor() {
  return <span className="inline-block w-0.5 h-4 bg-accent ml-0.5 align-middle animate-pulse" />;
}
