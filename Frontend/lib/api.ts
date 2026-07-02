export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

// ── Core sensor/fault types ─────────────────────────────────────────────────

export interface SensorReading {
  value?: number | null;
  unit?: string;
  normal?: [number, number] | null;
  critical?: [number, number] | null;
  device?: string;
  time?: string | null;
  status?: "good" | "warn" | "crit" | "unknown";
  error?: string;
}

export interface FaultEntry {
  code?: string;
  sensor?: string;
  severity?: string;
  source?: string;
  timestamp?: string;
  message?: string;
  value?: number;
}

export interface StatusResponse {
  sensors: Record<string, SensorReading>;
  faults: FaultEntry[];
  simulation_mode: string;
  timestamp: string;
}

export async function fetchStatus(): Promise<StatusResponse> {
  const res = await fetch(`${API_BASE}/status/json`, { cache: "no-store" });
  if (!res.ok) throw new Error(`status ${res.status}`);
  return res.json();
}

export async function fetchHealth(): Promise<{ status: string; timestamp: string }> {
  const res = await fetch(`${API_BASE}/health`, { cache: "no-store" });
  if (!res.ok) throw new Error(`health ${res.status}`);
  return res.json();
}

// ── Chronos health ──────────────────────────────────────────────────────────

export interface ChronosHealthResponse {
  status: "healthy" | "warming_up" | "stale";
  sensors_forecasted: number;
  sensors_total: number;
  sensors_with_warnings: number;
  sensors_with_critical: number;
  cache_age_seconds: number | null;
  timestamp: string;
}

export async function fetchChronosHealth(): Promise<ChronosHealthResponse> {
  const res = await fetch(`${API_BASE}/health/chronos`, { cache: "no-store" });
  if (!res.ok) throw new Error(`chronos health ${res.status}`);
  return res.json();
}

// ── Chronos forecast ────────────────────────────────────────────────────────

export interface SensorForecast {
  sensor: string;
  forecast_values: number[];
  lower_bound: number[];
  upper_bound: number[];
  horizon_seconds: number;
  minutes_to_warning: number | null;
  minutes_to_critical: number | null;
  anomaly_score: number;
  slope_per_step?: number;
  breach_source?: "current" | "chronos" | "slope" | "none";
  last_refreshed: number;
  /** Computed by backend: "normal" | "warning_approaching" | "critical_approaching" | "critical" */
  state: "normal" | "warning_approaching" | "critical_approaching" | "critical";
  mode: "normal" | "degradation";
}

export interface ChronosForecastResponse {
  forecasts: Record<string, SensorForecast>;
  mode: "normal" | "degradation";
  sensor_count: number;
}

export async function fetchChronosForecast(sensor?: string): Promise<ChronosForecastResponse | SensorForecast> {
  const url = sensor
    ? `${API_BASE}/chronos/forecast?sensor=${encodeURIComponent(sensor)}`
    : `${API_BASE}/chronos/forecast`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`chronos forecast ${res.status}`);
  return res.json();
}

// ── Chronos evaluation metrics ──────────────────────────────────────────────

export interface SensorEvaluation {
  sensor: string;
  mape: number;
  smape: number;
  q_loss: number;
  status: "good" | "better" | "bad";
  last_computed: number;
}

export interface ChronosEvaluationResponse {
  evaluations: Record<string, SensorEvaluation>;
  sensor_count: number;
}

export async function fetchChronosEvaluation(): Promise<ChronosEvaluationResponse> {
  const res = await fetch(`${API_BASE}/chronos/evaluation`, { cache: "no-store" });
  if (!res.ok) throw new Error(`chronos evaluation ${res.status}`);
  return res.json();
}


// ── Simulation mode ─────────────────────────────────────────────────────────

export interface SimulationModeResponse {
  mode: "normal" | "degradation";
}

export async function fetchSimulationMode(): Promise<SimulationModeResponse> {
  const res = await fetch(`${API_BASE}/simulation/mode`, { cache: "no-store" });
  if (!res.ok) throw new Error(`simulation mode ${res.status}`);
  return res.json();
}

export async function setSimulationMode(mode: "normal" | "degradation"): Promise<{ ok: boolean; mode: string }> {
  const res = await fetch(`${API_BASE}/simulation/mode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  if (!res.ok) throw new Error(`set mode ${res.status}`);
  return res.json();
}

/**
 * Ask the backend to immediately run a Chronos forecast refresh cycle.
 * Call this after a simulation mode change so stale forecast data is flushed fast.
 */
export async function forceChronosRefresh(): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(`${API_BASE}/chronos/refresh`, {
    method: "POST",
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`chronos refresh ${res.status}`);
  return res.json();
}

// ── Redis health ────────────────────────────────────────────────────────────

export interface RedisHealthResponse {
  status: "up" | "down" | "error";
  used_memory_human?: string;
  maxmemory_human?: string;
  active_sessions?: number;
  message?: string;
}

export async function fetchRedisHealth(): Promise<RedisHealthResponse> {
  const res = await fetch(`${API_BASE}/health/redis`, { cache: "no-store" });
  if (!res.ok) throw new Error(`redis health ${res.status}`);
  return res.json();
}

// ── Metrics ─────────────────────────────────────────────────────────────────

export interface MetricsResponse {
  averages_24h: {
    faithfulness?: number;
    answer_relevancy?: number;
    tool_precision?: number;
    overall_quality?: number;
    latency_ms?: number;
    steps_taken?: number;
  };
  timestamp: string;
}

export async function fetchMetrics(): Promise<MetricsResponse> {
  const res = await fetch(`${API_BASE}/metrics`, { cache: "no-store" });
  if (!res.ok) throw new Error(`metrics ${res.status}`);
  return res.json();
}

// ── Chat session ────────────────────────────────────────────────────────────

export async function clearChatSession(sessionId: string): Promise<void> {
  await fetch(`${API_BASE}/chat/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
}

export interface StoredChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  tool_count?: number;
}

export interface ChatHistoryResponse {
  session_id: string;
  messages: StoredChatMessage[];
  count: number;
}

export async function fetchChatHistory(
  sessionId: string,
  lastN?: number,
): Promise<ChatHistoryResponse> {
  const url = new URL(`${API_BASE}/chat/${encodeURIComponent(sessionId)}/history`);
  if (lastN) url.searchParams.set("last_n", String(lastN));
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) throw new Error(`chat history ${res.status}`);
  return res.json();
}

// ── Agent stream event types from /chat/stream (SSE) ───────────────────────

export type AgentEvent =
  | { type: "status"; message: string }
  | { type: "tool_start"; step: number; tool: string; args: Record<string, unknown> }
  | { type: "tool_end"; step: number; tool: string; args: Record<string, unknown>; result_preview: string; result_length: number }
  | { type: "answer_chunk"; text: string }
  | { type: "done"; answer: string; steps: unknown[]; total_steps: number; latency_ms: number; timestamp: string }
  | { type: "error"; message: string };

/**
 * Stream agent events from POST /chat/stream (SSE).
 * Supports Redis-backed session history via session_id.
 */
export async function streamChat(
  question: string,
  onEvent: (e: AgentEvent) => void,
  signal?: AbortSignal,
  sessionId = "ui-default",
): Promise<void> {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      session_id: sessionId,
      evaluate: true,
      use_history: true,
    }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`chat stream ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      for (const line of raw.split("\n")) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data:")) continue;
        const payload = trimmed.slice(5).trim();
        if (!payload) continue;
        try {
          onEvent(JSON.parse(payload) as AgentEvent);
        } catch {
          // ignore malformed chunk
        }
      }
    }
  }
}

// ── WebSocket alert stream from /ws/alerts ──────────────────────────────────

export interface AffectedSensor {
  sensor: string;
  current: number | null;
  warn_low: number | null;
  warn_high: number | null;
  crit_low: number | null;
  crit_high: number | null;
  minutes_to_warning: number | null;
  minutes_to_critical: number | null;
  cause: string;
}

export interface ChronosAlert {
  type: "chronos_alert" | "heartbeat";
  severity?: "WARNING" | "CRITICAL";
  sensor?: string;
  minutes_to_warning?: number;
  minutes_to_critical?: number;
  anomaly_score?: number;
  forecast_value?: number;
  auto_recovery?: boolean;
  cause?: string;
  affected_sensors?: AffectedSensor[];
  mode?: string;
  timestamp: string;
}

/**
 * Connect to the /ws/alerts WebSocket.
 * Returns a cleanup function to close the socket.
 */
export function connectAlertSocket(
  onAlert: (a: ChronosAlert) => void,
  onClose?: () => void,
): () => void {
  const wsBase = API_BASE.replace(/^http/, "ws");
  const ws = new WebSocket(`${wsBase}/ws/alerts`);

  ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data) as ChronosAlert;
      onAlert(data);
    } catch {
      // ignore bad frames
    }
  };

  ws.onclose = () => onClose?.();
  ws.onerror = () => ws.close();

  return () => ws.close();
}
