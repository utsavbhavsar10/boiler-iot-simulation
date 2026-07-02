# Chronos Implementation Audit — Phase & Feature Status

**Repo:** `Boiler-IOT-Simulation`
**Date:** 2026-06-23
**Scope:** Verify all 8 phases of `chronos_implementation_plan.md` against actual code, identify what works / what breaks, locate the duplicate-answer bug reported by user.

---

## TL;DR — The Duplicate-Answer Bug

**Bug found.** File: `assistant/agent/orchestrator.py`, function `run_stream()`, lines **504–507**.

The model's final text gets appended to `final_answer_parts` **twice**:
1. **First append (line 504–507)** — unconditional "fallback capture" that runs on every loop iteration whenever `text_parts` is non-empty.
2. **Second append (line 558–560)** — the `elif text_parts:` branch that fires on the final-answer turn.

Both branches execute on the same turn → `final_answer_parts = [text, text]` → the `done` event ships `answer = text + text` → frontend's `case "done"` (`ChatPanel.tsx:99-104`) overwrites the streamed text with the doubled string → **user sees the same answer twice**.

`run()` (non-stream) has the same dual-capture pattern (lines 312–313 + 365) but uses `=` assignment, not `append`, so it only overwrites — no duplication there. Only the streaming path is broken.

### Fix
In `run_stream()`, remove the early capture (lines 504–507). The `elif text_parts:` branch at 558–560 already covers the final-answer case. The early capture was meant to rescue text emitted alongside a tool call when the loop later exhausts — but it doesn't gate against the case where the same turn falls through to the `elif`.

Minimal patch:
```python
# DELETE lines 504–507 in run_stream()
# (the early `if text_parts: ... final_answer_parts.append(inline_text)` block)
```

Or, if you want to keep the fallback for mixed tool+text turns, gate it so it only fires when tool_calls is ALSO present:
```python
if text_parts and tool_calls:
    inline_text = "\n".join(p.text for p in text_parts).strip()
    if inline_text:
        final_answer_parts.append(inline_text)
```

---

## Phase-by-Phase Verification

| Phase | Status | Notes |
|---|---|---|
| **1. Setup** (deps, env vars) | ✅ Works | `chronos_service.py` imports `chronos.ChronosPipeline`, config knobs (`CHRONOS_MODEL`, `CHRONOS_DEVICE`, etc.) wired in `assistant/config.py` and consumed at `chronos_service.py:31-44`. |
| **2. Chronos Service** | ✅ Works | `chronos_service.py` implements `_fetch_influx_history`, `ChronosService.forecast_sensor/forecast_all_sensors`, `format_for_llm_context`. Uses InfluxDB (per plan deviation), not in-process SensorBuffer. Threshold map built from `SENSOR_NORMAL_RANGE`/`SENSOR_CRITICAL_RANGE` (single source of truth, per plan). |
| **3. Background Refresh** | ✅ Works | `refresh_loop()` at `chronos_service.py:434`, started as daemon thread in `api/chatbot_api.py:57-66`. Atomic update via `_cache_lock`. Exception-wrapped, never crashes. |
| **4a. predict_trend internals replaced** | ✅ Works | `tools/predict_trend.py:28-116` — Chronos primary path, `_legacy_predict_trend` fallback when cache empty. Signature preserved (`(sensor_name, window_minutes=30) -> str`). |
| **4b. get_chronos_forecast tool** | ✅ Works | `tools/chronos_tool.py` — supports `"all"` and single-sensor mode, fuzzy-match fallback, warming-up message. |
| **4c. Orchestrator registry** | ✅ Works | `orchestrator.py:40-46` — `get_chronos_forecast` registered. |
| **4d. Tool schema** | ⚠️ Not verified in this audit | Did not open `tool_schemas.py`. Plan says append a `FunctionDeclaration`. Verify Gemini actually sees it. |
| **5. Context Injection** | ⚠️ Partially works, **causes the duplicate bug** | Prepended per-`run()` to user turn (correct per plan). BUT `run_stream()` has the dual-append flaw described above. |
| **6. Evaluation** | ⚠️ Not verified | Plan calls for `evaluation/chronos_eval.py` + `EXPECTED_TOOLS_MAP` update. Files referenced in `CHRONOS_EXPLANATION.md`, not opened here. |
| **7. Fine-tuning (optional)** | N/A | Optional — skip until Phase 6 baseline shows it's needed. |
| **8. Deployment + /health/chronos** | ✅ Works | `/health/chronos` endpoint at `api/chatbot_api.py:101-150` returns proper `healthy`/`warming_up`/`stale` states with cache age. |

---

## Features That Work Correctly

1. **Chronos model load + 30s refresh cycle** — daemon thread, atomic cache swap, per-sensor exception isolation.
2. **InfluxDB history fetch** (`_fetch_influx_history`) — correct Flux query, sorted oldest-first.
3. **Threshold breach detection** — handles both `high` and `low` direction (e.g. `oxygen_level`, `condenser_vacuum`).
4. **Anomaly score** — IQR-based deviation against Chronos's expected step-0 distribution.
5. **`get_chronos_forecast`** tool with `all` + single-sensor modes + fuzzy match.
6. **`predict_trend`** Chronos-powered with legacy regression fallback during warmup.
7. **Non-stream `/chat` endpoint** (`run()`) — no duplicate.
8. **`/health/chronos`** — accurate cache age, warming_up vs stale logic.

---

## Features That Break Logic

### 🚨 BUG 1 — Duplicate streamed answer (HIGH severity, user-reported)

- **File:** `assistant/agent/orchestrator.py`
- **Lines:** 504-507 (early capture) collides with 558-560 (final answer branch)
- **Effect:** `done.answer` is the model's text concatenated with itself. Frontend's `case "done"` replaces streamed text with this doubled string. User sees answer twice.
- **Trigger:** every `/chat/stream` call where the model returns final text (i.e. every successful streamed answer).
- **Fix:** see "TL;DR" above.

### ⚠️ BUG 2 — Cache lock not held by readers (LOW severity)

- **Files:** `chronos_tool.py:48,60,103`, `predict_trend.py:55`, `orchestrator.py:256,460`, `chatbot_api.py:117,129,140-147`
- All read `chronos_cache` without `_cache_lock`. Writer at `chronos_service.py:467-469` does `clear() + update()` under lock. Between `clear()` and `update()` a reader can see an **empty cache** → falls back to "warming up" message or legacy regression mid-cycle.
- **Fix:** writer should build new dict and rebind reference (`chronos_cache = new_forecasts`) instead of clear+update. Or readers should snapshot under lock. Simpler: replace lines 467-469 with `with _cache_lock: chronos_cache.update(new_forecasts); for k in list(chronos_cache) - new_forecasts.keys(): chronos_cache.pop(k)` — never empty.

### ⚠️ BUG 3 — `predict_trend` legacy fallback used when cache populated but sensor missing (MEDIUM)

- **File:** `tools/predict_trend.py:55-57`
- Logic: `fc = chronos_cache.get(sensor_name); if fc is not None: ... else: legacy()`. If the cache is populated for 24 other sensors but missing this one (e.g. InfluxDB returned no history for it this cycle), falls back to legacy without telling the user. Behaviour silently changes.
- **Fix:** distinguish "cache fully empty" (warming up) from "this sensor not in cache" (unavailable) — return an explicit message in the second case rather than legacy.

### ⚠️ BUG 4 — Forecast context injected even when stale (MEDIUM)

- **Files:** `orchestrator.py:254-261, 458-465`
- `if chronos_cache:` is the only guard. If the refresh thread crashed and the cache is 10 minutes stale, the LLM still gets and cites old forecast data. The `/health/chronos` endpoint detects this, but the orchestrator does not.
- **Fix:** skip injection if `max(fc.last_refreshed) < time.time() - 120`.

### ⚠️ BUG 5 — Streaming `answer_chunk` byte-loop (LOW)

- **File:** `orchestrator.py:563-569`
- Iterates **character-by-character** building 6-char chunks, yielding one SSE event per chunk. For a 2000-char answer that's ~330 SSE events. Works but wasteful; not the cause of the duplicate.

---

## Recommended Action Order

1. **Fix BUG 1** (the duplicate) — 5 minute edit in `run_stream()`. This is what the user is hitting.
2. Fix BUG 2 (race) — readers can see empty cache between `clear()` and `update()`.
3. Fix BUG 4 (stale-forecast injection) — gate on `last_refreshed`.
4. Verify Phase 4d (tool_schemas.py has `get_chronos_forecast` `FunctionDeclaration`).
5. Run Phase 6 eval to confirm Chronos accuracy meets thresholds (MAPE<15%, lead≥10min, F1≥0.6).

---

## Quick Repro for BUG 1

```bash
curl -N -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"question":"What is current flue gas temp?","evaluate":false}'
```

Watch the SSE stream: `answer_chunk` events build up the answer once. Then the `done` event arrives with `"answer": "<TEXT><TEXT>"` — text duplicated. Frontend overwrites and shows the doubled string.
