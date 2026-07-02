"""
FastAPI — Boiler Agentic RAG API
Endpoints:
  POST /chat                  — run agent, returns answer + steps + eval scores
  POST /chat/stream           — SSE streaming agent with Redis chat history
  GET  /status                — live sensor snapshot (text)
  GET  /status/json           — structured sensor + fault JSON for dashboard
  GET  /metrics               — 24h evaluation averages from InfluxDB
  GET  /health                — service health check
  GET  /health/chronos        — Chronos forecast cache health
  GET  /health/redis          — Redis memory + session stats
  GET  /chronos/forecast      — full probabilistic forecast per sensor
  POST /simulation/mode       — switch simulator between Normal / Degradation
  GET  /simulation/mode       — current simulation mode
  DELETE /chat/{session_id}   — clear Redis chat session
  WS   /ws/chat               — WebSocket chat endpoint
  WS   /ws/alerts             — real-time Chronos alerts (degradation mode)
"""
import threading
import asyncio
import json
import re
import time
from datetime import datetime, UTC

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from influxdb_client import InfluxDBClient

from assistant.agent.orchestrator import BoilerAgentOrchestrator
from assistant.agent.tools.realtime_tool import fetch_realtime_sensors
from assistant.agent.tools.fault_history  import get_fault_history
from assistant.config import (
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    SENSOR_MEASUREMENTS, SENSOR_UNITS, SENSOR_NORMAL_RANGE, SENSOR_CRITICAL_RANGE,
    ALL_SENSOR_NAMES,
)
from evaluation.evaluator import BoilerEvaluator

# ── Chronos background service ─────────────────────────────────────────────────
from assistant.agent.chronos_service import (
    chronos_service,
    chronos_cache,
    chronos_eval_cache,
    refresh_loop,
    SensorForecast,
    SensorEvaluation,
    trigger_force_refresh,
    set_simulation_mode_ref,
)

# ── Alert manager (degradation mode + auto-recovery) ──────────────────────────
from assistant.agent.alert_manager import (
    alert_monitor_loop,
    register_websocket   as _register_alert_ws,
    deregister_websocket as _deregister_alert_ws,
    simulation_mode,     # shared dict {"mode": "normal"|"degradation"}
)

# ── Redis chat cache ────────────────────────────────────────────────────────────
from assistant.cache.chat_cache import chat_cache

# ──────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Boiler Agentic RAG — POC Standard",
    description=(
        "Fine-tuned Gemini 2.5 Flash + Chronos AI forecasting + "
        "Hybrid RAG + Redis chat history. "
        "Supports Normal and Degradation simulation modes."
    ),
    version="4.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Shared heavy objects (initialised once at startup) ─────────────────────────
agent     = BoilerAgentOrchestrator()
evaluator = BoilerEvaluator()
influx    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)


# ══════════════════════════════════════════════════════════════════════════════
# STARTUP — background threads
# ══════════════════════════════════════════════════════════════════════════════

@app.on_event("startup")
def start_background_threads():
    """
    Launch all daemon background threads at FastAPI startup.
    All threads are daemon=True → exit automatically when the process stops.

    Thread 1 — chronos-refresh: fetches InfluxDB history + runs Chronos
               forecasts for all sensors every 30s.
    Thread 2 — alert-monitor:   checks chronos_cache every 15s. When in
               Degradation mode and minutes_to_critical ≤ 5, fires alert,
               writes to InfluxDB, broadcasts to WebSocket, auto-recovers.
    """
    t1 = threading.Thread(target=refresh_loop,       daemon=True, name="chronos-refresh")
    t2 = threading.Thread(target=alert_monitor_loop, daemon=True, name="alert-monitor")
    t1.start()
    t2.start()
    # Inject the shared simulation_mode dict into chronos_service so the refresh
    # loop can choose the correct InfluxDB history window (2 min in normal mode).
    set_simulation_mode_ref(simulation_mode)
    print("🚀 Background threads started: chronos-refresh | alert-monitor")


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now(UTC).isoformat()}


@app.get("/health/chronos")
def health_chronos():
    """
    Chronos cache health:
      status            — 'healthy' | 'warming_up' | 'stale'
      sensors_forecasted — count with valid forecasts
      sensors_total      — expected total
      sensors_with_warnings  — count approaching warning threshold
      sensors_with_critical  — count approaching critical threshold
      cache_age_seconds  — seconds since last successful refresh
    """
    stale_threshold = 45  # seconds (3 × 15s refresh interval)

    if not chronos_cache:
        return {
            "status": "warming_up",
            "sensors_forecasted": 0,
            "sensors_total": len(ALL_SENSOR_NAMES),
            "sensors_with_warnings": 0,
            "sensors_with_critical": 0,
            "cache_age_seconds": None,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    latest_refresh = max(
        (fc.last_refreshed for fc in chronos_cache.values()), default=0.0
    )
    cache_age = round(time.time() - latest_refresh, 1)
    status    = "stale" if cache_age > stale_threshold else "healthy"

    return {
        "status":               status,
        "sensors_forecasted":   len(chronos_cache),
        "sensors_total":        len(ALL_SENSOR_NAMES),
        "sensors_with_warnings": sum(
            1 for fc in chronos_cache.values() if fc.minutes_to_warning is not None
        ),
        "sensors_with_critical": sum(
            1 for fc in chronos_cache.values() if fc.minutes_to_critical is not None
        ),
        "cache_age_seconds":    cache_age,
        "timestamp":            datetime.now(UTC).isoformat(),
    }


@app.get("/health/redis")
def health_redis():
    """Redis memory + active session stats for monitoring dashboards."""
    return chat_cache.memory_info()


# ══════════════════════════════════════════════════════════════════════════════
# CHRONOS FORECAST ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

def _classify_forecast_state(fc: SensorForecast) -> str:
    """
    Map Chronos forecast to a dashboard-friendly state label.

    Delegates to fc.state (set by ChronosService.forecast_sensor) which
    correctly marks 'critical' when sensor is already past critical threshold.
    Falls back to minutes-based logic for any cached forecasts without state.
    """
    dataclass_state = getattr(fc, "state", None)
    if dataclass_state:
        return dataclass_state
    # Legacy fallback
    if fc.minutes_to_critical is not None and fc.minutes_to_critical <= 0.2:
        return "critical"
    if fc.minutes_to_critical is not None:
        return "critical_approaching"
    if fc.minutes_to_warning is not None:
        return "warning_approaching"
    return "normal"


def _enrich_forecast(fc: SensorForecast, sensor_name: str) -> dict:
    return {
        "sensor":               sensor_name,
        "forecast_values":      fc.forecast_values,
        "lower_bound":          fc.lower_bound,
        "upper_bound":          fc.upper_bound,
        "horizon_seconds":      fc.horizon_seconds,
        "minutes_to_warning":   fc.minutes_to_warning,
        "minutes_to_critical":  fc.minutes_to_critical,
        "steps_to_warning":     fc.steps_to_warning,
        "steps_to_critical":    fc.steps_to_critical,
        "anomaly_score":        fc.anomaly_score,
        "slope_per_step":       fc.slope_per_step,
        "breach_source":        fc.breach_source,
        "last_refreshed":       fc.last_refreshed,
        "state":                _classify_forecast_state(fc),
        "mode":                 simulation_mode.get("mode", "normal"),
    }



@app.get("/chronos/forecast")
def get_chronos_forecast_endpoint(sensor: str = None):
    """
    Returns the current Chronos probabilistic forecast.

    Query params:
      ?sensor=main_steam_temp_boiler  — single sensor
      (no param)                      — all sensors sorted by urgency

    Response fields:
      forecast_values    — 20-step point forecast (median)
      lower_bound        — 10th percentile confidence band
      upper_bound        — 90th percentile confidence band
      minutes_to_warning — predicted minutes to warning threshold (null = never)
      minutes_to_critical — predicted minutes to critical threshold (null = never)
      anomaly_score      — 0.0–1.0 (higher = more anomalous)
      state              — "normal" | "warning_approaching" | "critical_approaching" | "critical"
      mode               — current simulation mode
    """
    mode = simulation_mode.get("mode", "normal")

    if not chronos_cache:
        return {"error": "Chronos cache warming up — wait ~30s after startup."}

    if sensor:
        fc = chronos_cache.get(sensor)
        if not fc:
            available = sorted(chronos_cache.keys())
            return {
                "error": f"No forecast for '{sensor}'. Available: {available}"
            }
        return _enrich_forecast(fc, sensor)

    # All sensors — sort by urgency (critical first, then warning, then normal)
    def urgency(item):
        _, fc = item
        if fc.minutes_to_critical is not None:
            return (0, fc.minutes_to_critical)
        if fc.minutes_to_warning is not None:
            return (1, fc.minutes_to_warning)
        return (2, 9999.0)

    sorted_forecasts = sorted(chronos_cache.items(), key=urgency)
    result = {name: _enrich_forecast(fc, name) for name, fc in sorted_forecasts}
    return {"forecasts": result, "mode": mode, "sensor_count": len(result)}


@app.get("/chronos/evaluation")
def get_chronos_evaluation():
    """
    Return backtesting evaluation metrics (MAPE, sMAPE, Q-Loss) for all forecasted sensors.
    Enables checking if the Chronos model predictions are performing well.
    """
    if not chronos_eval_cache:
        return {"error": "Evaluation cache warming up — wait for first refresh cycle."}
    
    sorted_evals = sorted(chronos_eval_cache.items(), key=lambda x: x[0])
    result = {name: {
        "sensor": ev.sensor,
        "mape": ev.mape,
        "smape": ev.smape,
        "q_loss": ev.q_loss,
        "status": ev.status,
        "last_computed": ev.last_computed
    } for name, ev in sorted_evals}
    
    return {"evaluations": result, "sensor_count": len(result)}



# ══════════════════════════════════════════════════════════════════════════════
# SIMULATION MODE — Dual-mode (Normal / Degradation)
# ══════════════════════════════════════════════════════════════════════════════

class ModeRequest(BaseModel):
    mode: str  # "normal" | "degradation"


@app.post("/simulation/mode")
def set_simulation_mode(req: ModeRequest):
    """
    Switch the boiler simulator between Normal and Degradation mode.

    In Normal mode:
      - Sensors oscillate within SENSOR_NORMAL_RANGE.
      - Chronos predicts time-to-warning/critical (typically "never").

    In Degradation mode:
      - The simulator ramps main_steam_temp_boiler toward 580°C (+2°C/cycle).
      - Chronos detects the trend and predicts minutes_to_critical ≤ 5.
      - Alert manager fires a CHRONOS_CRITICAL_FORECAST alert.
      - Auto-recovery resets mode to "normal" automatically.
    """
    if req.mode not in ("normal", "degradation"):
        return {"error": "mode must be 'normal' or 'degradation'"}
    simulation_mode["mode"] = req.mode
    print(f"🎛️  Simulation mode → {req.mode.upper()}")
    # Wake up Chronos refresh loop immediately so it picks up the new mode's
    # history window (2 min for normal, full window for degradation) within seconds.
    trigger_force_refresh()
    return {"ok": True, "mode": req.mode}


@app.get("/simulation/mode")
def get_simulation_mode():
    """Return the current simulation mode."""
    return simulation_mode


@app.post("/chronos/refresh")
def force_chronos_refresh():
    """
    Trigger an immediate Chronos forecast refresh cycle.
    Useful after a simulation mode change to flush stale forecast data fast.
    The refresh loop will wake up and re-run within a few seconds.
    """
    trigger_force_refresh()
    return {
        "ok": True,
        "message": "Chronos refresh triggered — cache will update within ~15s",
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# CHAT ENDPOINTS (with Redis history)
# ══════════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    question:    str
    session_id:  str  = "default"
    evaluate:    bool = True
    use_history: bool = True   # set False to run without chat context


def _split_contexts(tool_name: str, raw: str) -> list:
    """Split a tool result into per-document contexts for RAGAS."""
    if not raw:
        return []
    if tool_name == "search_knowledge_base":
        chunks = re.split(r"\n--- .*? ---\n", raw)
        return [c.strip() for c in chunks if c.strip()]
    if tool_name == "fetch_realtime_sensors":
        return [b.strip() for b in raw.split("\n\n") if b.strip()]
    return [raw.strip()]


def _build_contexts(steps: list) -> list:
    """Build full, chunked context list from agent steps."""
    contexts = []
    for step in steps:
        raw = step.get("result") or step.get("result_preview", "")
        contexts.extend(_split_contexts(step["tool"], raw))
    return contexts


@app.post("/chat")
def chat(request: ChatRequest):
    """
    Main chat endpoint (non-streaming).
    Loads Redis history → runs ReAct agent → saves turns back to Redis.
    Returns: answer, steps, eval_scores, latency_ms.
    """
    # Load Redis history
    history = chat_cache.get_history(request.session_id) if request.use_history else []
    summary = chat_cache.get_summary(request.session_id) if request.use_history else None

    # Save user turn before inference (recoverable if model fails)
    chat_cache.append_turn(request.session_id, "user", request.question)

    # Run agent
    result = agent.run(request.question, history=history, summary=summary)

    # Save assistant turn
    tools_used = len(result.get("steps", []))
    chat_cache.append_turn(
        request.session_id, "assistant",
        result["answer"], tool_count=tools_used,
    )

    # Evaluate
    contexts     = _build_contexts(result["steps"])
    tools_called = [step["tool"] for step in result["steps"]]
    had_tool_call = len(result["steps"]) > 0

    eval_scores = {}
    if request.evaluate:
        eval_contexts = contexts or [
            "(agent answered without calling any tool — no retrieved context)"
        ]
        eval_scores = evaluator.evaluate_answer(
            question=request.question,
            answer=result["answer"],
            contexts=eval_contexts,
            latency_ms=result["latency_ms"],
            steps_taken=result["total_steps"],
            tools_called=tools_called,
            had_tool_call=had_tool_call,
        )

    return {
        "question":    request.question,
        "answer":      result["answer"],
        "steps":       result["steps"],
        "total_steps": result["total_steps"],
        "latency_ms":  result["latency_ms"],
        "eval_scores": eval_scores,
        "timestamp":   result["timestamp"],
        "session_id":  request.session_id,
    }


def _run_eval_async(question: str, answer: str, steps: list, latency_ms: float):
    """Run RAGAS eval in a background thread so it survives client disconnect."""
    try:
        contexts     = _build_contexts(steps)
        tools_called = [s["tool"] for s in steps]
        had_tool_call = len(steps) > 0
        eval_contexts = contexts or [
            "(agent answered without calling any tool — no retrieved context)"
        ]
        evaluator.evaluate_answer(
            question=question,
            answer=answer,
            contexts=eval_contexts,
            latency_ms=latency_ms,
            steps_taken=len(steps),
            tools_called=tools_called,
            had_tool_call=had_tool_call,
        )
    except Exception as exc:
        print(f"⚠️  Stream eval failed: {exc}")


@app.post("/chat/stream")
def chat_stream(request: ChatRequest):
    """
    Server-Sent Events streaming chat endpoint with Redis history.

    Flow:
      1. Load last 20 turns from Redis for session_id.
      2. Prepend history to agent question.
      3. Stream tool events + answer chunks as SSE.
      4. Save user + assistant turns to Redis on completion.
      5. Run RAGAS eval in background thread.
    """
    history = chat_cache.get_history(request.session_id) if request.use_history else []
    summary = chat_cache.get_summary(request.session_id) if request.use_history else None

    # Save user turn immediately (before inference)
    chat_cache.append_turn(request.session_id, "user", request.question)

    final_state = {"answer": "", "steps": [], "latency": 0.0}

    def event_gen():
        try:
            for evt in agent.run_stream(
                request.question,
                history=history,
                summary=summary,
            ):
                if evt.get("type") == "done":
                    final_state["answer"]  = evt.get("answer", "")
                    final_state["steps"]   = evt.get("steps", [])
                    final_state["latency"] = evt.get("latency_ms", 0.0)

                    # Save assistant turn to Redis
                    chat_cache.append_turn(
                        request.session_id, "assistant",
                        final_state["answer"],
                        tool_count=len(final_state["steps"]),
                    )

                    # Fire RAGAS eval in background
                    if request.evaluate:
                        threading.Thread(
                            target=_run_eval_async,
                            args=(
                                request.question,
                                final_state["answer"],
                                final_state["steps"],
                                final_state["latency"],
                            ),
                            daemon=True,
                            name="ragas-eval-stream",
                        ).start()

                yield f"data: {json.dumps(evt)}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/chat/{session_id}")
def clear_chat(session_id: str):
    """Clear Redis chat history for a session (user pressed 'New Chat')."""
    chat_cache.clear(session_id)
    return {"ok": True, "session_id": session_id}


@app.get("/chat/{session_id}/history")
def get_chat_history(session_id: str, last_n: int | None = None):
    """Return prior chat turns for session_id (oldest → newest) from Redis."""
    history = chat_cache.get_history(session_id, last_n=last_n)
    return {
        "session_id": session_id,
        "messages":   history,
        "count":      len(history),
    }


@app.get("/metrics")
def get_metrics_endpoint():
    """Returns 24h average evaluation metrics from InfluxDB."""
    query = f'''
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -24h)
      |> filter(fn: (r) => r["_measurement"] == "chatbot_evaluation")
      |> filter(fn: (r) => r["_field"] == "faithfulness" or
                           r["_field"] == "answer_relevancy" or
                           r["_field"] == "tool_precision" or
                           r["_field"] == "overall_quality" or
                           r["_field"] == "latency_ms" or
                           r["_field"] == "steps_taken")
      |> mean()
    '''
    try:
        tables = influx.query_api().query(query)
        averages = {}
        for table in tables:
            for record in table.records:
                averages[record.get_field()] = round(record.get_value(), 3) if record.get_value() is not None else None
        return {"averages_24h": averages, "timestamp": datetime.now(UTC).isoformat()}
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# STATUS / SENSOR ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/status")
def status():
    """Returns live sensor readings and recent faults (text — used by Streamlit / LLM)."""
    return {
        "sensors":   fetch_realtime_sensors(),
        "faults":    get_fault_history(minutes=60),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _classify(name: str, value):
    if value is None:
        return "unknown"
    crit = SENSOR_CRITICAL_RANGE.get(name)
    if crit and (value < crit[0] or value > crit[1]):
        return "crit"
    norm = SENSOR_NORMAL_RANGE.get(name)
    if norm and (value < norm[0] or value > norm[1]):
        return "warn"
    return "good"


def _query_latest_sensors() -> dict:
    """Structured per-sensor snapshot from InfluxDB. Used by dashboard."""
    out  = {}
    qapi = influx.query_api()
    for _, cfg in SENSOR_MEASUREMENTS.items():
        measurement = cfg["measurement"]
        device      = cfg["device"]
        for sensor in cfg["sensors"]:
            flux = f'''
            from(bucket: "{INFLUX_BUCKET}")
              |> range(start: -5m)
              |> filter(fn: (r) => r["_measurement"] == "{measurement}")
              |> filter(fn: (r) => r["sensor"] == "{sensor}")
              |> filter(fn: (r) => r["_field"] == "value")
              |> last()
            '''
            entry = {
                "value":    None,
                "unit":     SENSOR_UNITS.get(sensor, ""),
                "normal":   SENSOR_NORMAL_RANGE.get(sensor),
                "critical": SENSOR_CRITICAL_RANGE.get(sensor),
                "device":   device,
                "time":     None,
                "status":   "unknown",
            }
            try:
                tables = qapi.query(flux)
                for table in tables:
                    for record in table.records:
                        v = round(record.get_value(), 2)
                        entry["value"]  = v
                        entry["time"]   = str(record.get_time())
                        entry["status"] = _classify(sensor, v)
            except Exception as exc:
                entry["error"] = str(exc)
            out[sensor] = entry
    return out


def _query_recent_faults(minutes: int = 60) -> list:
    """Structured fault list from InfluxDB. Used by dashboard."""
    flux = f'''
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -{minutes}m)
      |> filter(fn: (r) => r["_measurement"] == "fault_events")
      |> filter(fn: (r) => r["_field"] == "message")
      |> sort(columns: ["_time"], desc: true)
      |> limit(n: 50)
    '''
    faults = []
    try:
        tables = influx.query_api().query(flux)
        for table in tables:
            for record in table.records:
                faults.append({
                    "timestamp": str(record.get_time()),
                    "code":      record.values.get("fault_code", "UNKNOWN"),
                    "severity":  record.values.get("severity", "UNKNOWN"),
                    "sensor":    record.values.get("sensor", ""),
                    "source":    record.values.get("source", "simulator"),
                    "message":   record.get_value(),
                })
    except Exception as exc:
        return [{"code": "QUERY_ERROR", "severity": "WARNING",
                 "sensor": "", "message": str(exc),
                 "timestamp": datetime.now(UTC).isoformat()}]
    return faults


@app.get("/status/json")
def status_json(faults_minutes: int = 60):
    """Structured JSON snapshot for dashboard UIs (Next.js / Grafana)."""
    return {
        "sensors":         _query_latest_sensors(),
        "faults":          _query_recent_faults(faults_minutes),
        "simulation_mode": simulation_mode.get("mode", "normal"),
        "timestamp":       datetime.now(UTC).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket chat endpoint (non-streaming, one round-trip per message)."""
    await websocket.accept()
    try:
        while True:
            data     = await websocket.receive_text()
            payload  = json.loads(data)
            question = payload.get("question", "")
            sid      = payload.get("session_id", "ws-default")
            history  = chat_cache.get_history(sid)
            summary  = chat_cache.get_summary(sid)
            result   = agent.run(question, history=history, summary=summary)
            chat_cache.append_turn(sid, "user",      question)
            chat_cache.append_turn(sid, "assistant", result["answer"],
                                   tool_count=len(result["steps"]))
            await websocket.send_json({
                "answer":      result["answer"],
                "steps":       result["steps"],
                "latency_ms":  result["latency_ms"],
                "timestamp":   result["timestamp"],
            })
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """
    Real-time alert WebSocket for the dashboard.

    Clients connect once and receive JSON events whenever the alert_manager
    detects an imminent critical breach in Degradation mode.

    Event shape:
    {
      "type":                "chronos_alert",
      "sensor":              "main_steam_temp_boiler",
      "minutes_to_critical": 3.2,
      "anomaly_score":       0.91,
      "forecast_value":      572.4,
      "auto_recovery":       true,
      "timestamp":           "2026-06-23T07:00:00Z"
    }

    Heartbeat (every 30s):
    {
      "type":      "heartbeat",
      "mode":      "degradation",
      "timestamp": "..."
    }
    """
    await websocket.accept()
    _register_alert_ws(websocket)
    try:
        while True:
            # Send heartbeat every 30s to keep connection alive
            await asyncio.sleep(30)
            await websocket.send_json({
                "type":      "heartbeat",
                "mode":      simulation_mode.get("mode", "normal"),
                "timestamp": datetime.now(UTC).isoformat(),
            })
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _deregister_alert_ws(websocket)