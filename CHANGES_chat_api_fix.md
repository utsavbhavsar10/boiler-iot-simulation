# Chat API Fix — Why `/chat` Was Failing and What Changed

**Date:** 2026-06-11
**Files touched:** `api/chatbot_api.py`, `assistant/agent/orchestrator.py`

This document explains the bugs that broke the `/chat` endpoint, the root-cause
investigation, and every change applied to fix them.

---

## Symptom

Calling `POST /chat` on the FastAPI server returned a **500 error**. After the
first fix it returned `200` but with a useless fallback answer
(*"I gathered the following data but reached the maximum reasoning steps…"*) —
the agent never actually called any tool.

---

## Root Causes (3 separate bugs, stacked)

### Bug 1 — `TypeError` 500 crash: wrong number of arguments

**File:** `api/chatbot_api.py`

The endpoint called the agent with two arguments:

```python
result = agent.run(request.question, request.session_id)
```

But `BoilerAgentOrchestrator.run()` is defined to accept only one:

```python
def run(self, user_question: str) -> dict:
```

**Error produced:**

```
TypeError: BoilerAgentOrchestrator.run() takes 2 positional arguments but 3 were given
```

This crashed every single `/chat` request before any agent logic ran. The
WebSocket handler (`/ws/chat`) already called it correctly with one argument, so
the bug was only in the REST endpoint.

**Fix:** drop the unused `session_id` argument.

```python
# before
result = agent.run(request.question, request.session_id)
# after
result = agent.run(request.question)
```

---

### Bug 2 — `AttributeError` on text responses

**File:** `assistant/agent/orchestrator.py`

After fixing Bug 1, the loop crashed while inspecting the model's response:

```python
tool_calls = [
    part for part in content.parts
    if hasattr(part, "function_call") and part.function_call.name
]
```

**Error produced:**

```
AttributeError: 'NoneType' object has no attribute 'name'
```

**Why:** On a Vertex AI response `Part`, the `function_call` attribute *always
exists*, so `hasattr(part, "function_call")` is always `True`. For a plain text
part, `function_call` is `None`, so reading `.name` on it throws. The `hasattr`
check was the wrong guard.

**Fix:** use `getattr` to test for a truthy `function_call` before reading
`.name`.

```python
tool_calls = [
    part for part in content.parts
    if getattr(part, "function_call", None) and part.function_call.name
]
```

---

### Bug 3 — Model returned an EMPTY response (the real puzzle)

**File:** `assistant/agent/orchestrator.py` (the `system_instruction`)

With the crashes gone, `/chat` returned `200` but the model produced an **empty
candidate** every time:

```
finish_reason = STOP
parts = [ <one part with text="" and no function_call> ]
```

So the loop logged *"Empty response from Gemini"*, made zero tool calls, and
returned the max-steps fallback text.

#### Investigation

The fine-tuned Gemini endpoint is **brittle to system-instruction content**:
certain lines in the prompt make it emit an empty candidate instead of a real
answer or a tool call. This was confirmed by bisecting the instruction against
the **live endpoint** (each variant run 4–5 times for stability):

| System instruction sent to the model        | Result            |
| -------------------------------------------- | ----------------- |
| Persona only                                 | tool call ✅       |
| Short persona + rules (no problem lines)     | tool call ✅       |
| Rules containing `ALWAYS call search_knowledge_base` | **EMPTY** ❌ |
| Rules containing `Be specific with numbers: say "pressure is 18.2 bar…"` | **EMPTY** ❌ |
| Same rules with both lines removed           | tool call ✅       |

**Two independent triggers were found, each reproducible 4–5 out of 5 runs:**

1. **`ALWAYS call search_knowledge_base …`** — the instruction told the model to
   always call a tool named `search_knowledge_base`, but that tool is **commented
   out** of both `tool_schemas.py` (`BOILER_AGENT_TOOLS`) and the
   `TOOL_REGISTRY`. Instructing the model to always call an *undeclared* function
   makes it produce an empty candidate.

2. **`Be specific with numbers: say "pressure is 18.2 bar, 29% above the 14 bar
   limit" not "pressure is high"`** — this example line independently caused the
   same empty output. (Even a reworded version of the same idea still triggered
   it.) This is model-internal brittleness from the fine-tuning, not a logic
   error.

#### Fix

Removed both offending lines from the `system_instruction`. The behaviour rules
were renumbered accordingly. The remaining instruction (persona + tool-calling
rules + output structure + emoji severity markers) is verified to call tools
correctly.

```text
Your behaviour rules:
1. ALWAYS call fetch_realtime_sensors first for any question about current conditions
2. Call get_fault_history when the user asks about recent events or patterns
3. Call predict_trend when a sensor is moving toward a threshold or user asks about future risk
4. After collecting data from tools, synthesise a complete, actionable answer
5. Structure answers as: Current Status → Diagnosis → Root Cause → Immediate Actions → Prevention
6. Mark CRITICAL faults clearly with 🚨, WARNING with ⚠️, normal with ✅
```

> Note: the model still cites exact numbers in its answers on its own — dropping
> the "be specific" rule did not reduce answer quality.

---

## Verification

Final end-to-end test through the FastAPI `TestClient` against `POST /chat`:

- **Status:** `200`
- **Tool called:** `fetch_realtime_sensors` (the agent now actually runs the
  ReAct loop)
- **Answer:** a structured, grounded response with real sensor values and
  severity markers, e.g.:

```
🚨 CRITICAL SAFETY ALERT 🚨
Current Status:
- main_steam_temp_boiler: 547.01 °C (normal: 535–545 °C) — HIGH
- feedwater_temp: 285.74 °C (normal: 270–285 °C) — HIGH
...
```

---

## Summary of Changes

| # | File                                | Change                                                                 | Reason                                                        |
| - | ----------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------ |
| 1 | `api/chatbot_api.py`                | `agent.run(request.question, request.session_id)` → `agent.run(request.question)` | `run()` takes only one argument — extra arg caused a `TypeError` 500. |
| 2 | `assistant/agent/orchestrator.py`   | `hasattr(part, "function_call")` → `getattr(part, "function_call", None)` | `function_call` is always present but `None` on text parts; reading `.name` raised `AttributeError`. |
| 3 | `assistant/agent/orchestrator.py`   | Removed the `search_knowledge_base` rule from `system_instruction`      | Instructs the model to call an undeclared/disabled tool → model returns an empty response. |
| 4 | `assistant/agent/orchestrator.py`   | Removed the `Be specific with numbers: "…18.2 bar…"` rule from `system_instruction` | This line independently caused the fine-tuned model to return an empty response. |

---

## Recommendations / Follow-ups

- **This tuned endpoint is sensitive to its system prompt.** Validate any
  `system_instruction` edits against the live endpoint before deploying. Ideally,
  match the exact prompt format the model was fine-tuned with.
- **If `search_knowledge_base` is re-enabled,** declare it in `tool_schemas.py`
  (`BOILER_AGENT_TOOLS`) and add it to `TOOL_REGISTRY` *at the same time* you add
  it back to the instruction — never instruct a tool that isn't declared.
- **Consider a guard in the ReAct loop** so an empty candidate is retried or
  surfaced as a clear error, instead of silently returning the "max steps"
  placeholder answer.
