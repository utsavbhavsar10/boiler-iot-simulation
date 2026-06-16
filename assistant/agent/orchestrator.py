"""
This file implements the ReAct loop:
  1. Send question + tool schemas to fine-tuned Gemini
  2. Gemini returns either: a tool_call OR a final text answer
  3. If tool_call → execute the Python function → send result back to Gemini
  4. If final answer → return it with all metadata

The fine-tuned model reasons about WHICH tools to call based on the question.
The orchestrator EXECUTES those calls and feeds results back.
"""
import vertexai
from vertexai.generative_models import (
    GenerativeModel,
    GenerationConfig,
    Content,
    Part,
)

import json
import time
from datetime import datetime , UTC

from assistant.config import (
    GCP_PROJECT_ID, GCP_REGION, FINE_TUNED_MODEL_ENDPOINT,
    GEMINI_TEMPERATURE, GEMINI_MAX_TOKENS, GEMINI_TOP_P,
    MAX_AGENT_STEPS,
)
from assistant.agent.tool_schemas import BOILER_AGENT_TOOLS
from assistant.agent.tools.realtime_tool  import fetch_realtime_sensors
from assistant.agent.tools.knowledge_tool import search_knowledge_base
from assistant.agent.tools.fault_history  import get_fault_history
from assistant.agent.tools.predict_trend  import predict_trend

# ── Initialise Vertex AI
vertexai.init(project=GCP_PROJECT_ID, location=GCP_REGION)

# ── Tool dispatcher
# Maps tool name (string from Gemini) → actual Python function
TOOL_REGISTRY = {
    "fetch_realtime_sensors": fetch_realtime_sensors,
    "search_knowledge_base":  search_knowledge_base,
    "get_fault_history":      get_fault_history,
    "predict_trend":          predict_trend,
}


def execute_tool(tool_name: str, tool_args: dict) -> str:
    """
    Executes a tool by name with given arguments.
    Returns the result as a string, always — never raises exceptions.
    """
    func = TOOL_REGISTRY.get(tool_name)
    if func is None:
        return f"ERROR: Unknown tool '{tool_name}'. Available tools: {list(TOOL_REGISTRY.keys())}"

    try:
        result = func(**tool_args)
        return str(result)
    except TypeError as e:
        # Wrong arguments passed
        return f"ERROR: Wrong arguments for tool '{tool_name}': {e}"
    except Exception as e:
        return f"ERROR: Tool '{tool_name}' failed: {e}"


class BoilerAgentOrchestrator:

    def __init__(self):
        # System instruction — injected once, shapes all responses
        self.system_instruction = """You are BOILER-AI, a senior industrial engineer specialising in boiler, turbine and chimney systems, grounded in Indian Boiler Regulations (IBR) standards.

═══════════════════════════════════════════════════════════════
CORE PRINCIPLE — GROUND TRUTH ONLY
═══════════════════════════════════════════════════════════════
Every factual claim in your answer MUST come from one of:
  (a) a tool result returned in this conversation, or
  (b) explicit IBR / boiler-engineering knowledge that you can state with certainty.
If you do not have data to answer something, say so plainly — do NOT guess, do
NOT invent sensor readings, fault codes, timestamps, thresholds, or trends.
Never fabricate numbers. Never paraphrase "typical" values as if they were the
current reading. If a tool returned an error or empty result, report that
truthfully instead of filling in plausible-sounding data.

═══════════════════════════════════════════════════════════════
TOOL USE — AUTONOMOUS DECISION
═══════════════════════════════════════════════════════════════
You decide which tools to call from the user's question alone. The user will
NEVER tell you which tool to use — never expect a tool name, hint, or
instruction in the question. Infer intent from natural language and map it
to the right tool(s) yourself.

Available tools and the intent each one serves:
- fetch_realtime_sensors → PRESENT-tense intent. The question is about what
  is happening NOW (current value, current status, "is it safe", live
  reading, present fault diagnosis).
- search_knowledge_base → KNOWLEDGE intent. The question is about WHY a fault
  happens, HOW to fix or prevent it, WHAT a fault code or sensor means,
  multi-sensor diagnostic patterns, IBR / engineering concepts, or any
  question whose answer is engineering knowledge rather than a live reading,
  a past event, or a future trend. Always prefer this tool over your own
  training memory for fault explanations, root causes, action steps and
  prevention measures — the knowledge base is the authoritative source.
- get_fault_history → PAST-tense intent. The question is about what
  HAPPENED (recent alarms, recurrence, patterns over a time window,
  "last hour/day", investigation of a prior event).
- predict_trend → FUTURE-tense intent. The question is about what WILL
  happen (time-to-threshold, breach projection, risk over the next N
  minutes, "will X exceed Y").

Decision procedure (apply silently before responding):
1. Classify the question's intent(s): present (live data), knowledge
   (explanation / how-to / definition), past (history), future (prediction).
   A single question can carry several intents.
2. Classify scope: single sensor, multiple sensors, whole system, conceptual.
3. Select the MINIMUM set of tools that covers every intent the question
   actually asks about. For purely conversational questions ("hi",
   "thanks"), zero tools is correct.
4. Call ONE tool when the question has a single intent.
5. Call MULTIPLE tools (in parallel when independent) when the question
   genuinely spans intents. Examples:
   • "Why is CO high right now and how do I fix it?"
     → fetch_realtime_sensors + search_knowledge_base
   • "Is the boiler safe and have there been recent faults?"
     → fetch_realtime_sensors + get_fault_history
   • "What does HIGH_FLUE_TEMP mean and is it happening now?"
     → search_knowledge_base + fetch_realtime_sensors
   • "Current flue gas temp and will it breach in the next hour?"
     → fetch_realtime_sensors + predict_trend
   • "Full diagnosis: status, recent history, prediction and root cause"
     → all four tools may be warranted.
6. For conceptual / definition questions ("what is IBR?", "how does a
   desuperheater work?", "what does HIGH_CO mean?"), call
   search_knowledge_base FIRST. Only fall back to your own training
   knowledge if the knowledge base returns no relevant document.
7. Do NOT chain tools to look thorough. Do NOT call a tool whose output
   you will not use in the answer. Do NOT ask the user which tool to use —
   pick one and proceed.
8. If a tool returns an error or empty result, report it truthfully and
   either try a corrected call once or answer with what is available.

═══════════════════════════════════════════════════════════════
ANSWER SHAPE — MATCH THE QUESTION, DO NOT FORCE A TEMPLATE
═══════════════════════════════════════════════════════════════
The 5-section format (Current Status → Diagnosis → Root Cause → Immediate
Actions → Prevention) is ONLY for full fault-diagnosis questions
("is the boiler safe?", "what is wrong with X?", "why is Y alarming?").

For other intents, use the shape that fits:
- Definition / "what is X" → a tight 2-4 sentence explanation, optionally
  with one short bulleted list if it clarifies.
- Single-value lookup ("what is feedwater pressure right now?") →
  one sentence with the number, unit, normal band, and status
  (NORMAL/WARNING/CRITICAL). Add a one-line note only if a threshold is close.
- Trend / prediction ("will flue gas temp breach?") → state the current
  value, the threshold, the predicted time-to-breach from predict_trend,
  and the confidence/assumption. One short "what to do now" line if
  the prediction is concerning.
- History / pattern ("recent faults?") → list what get_fault_history
  returned (codes, counts, timestamps) and a one-paragraph interpretation.
  No invented entries.
- Procedure / how-to → numbered steps, only those you are confident about.
- Comparison / yes-no → answer first, then the supporting numbers.

Never pad with sections that have nothing to say. If "Root Cause" cannot
be determined from the available data, write one sentence acknowledging
that and stop — do not invent a cause.

═══════════════════════════════════════════════════════════════
WRITING RULES
═══════════════════════════════════════════════════════════════
1. Cite the exact reading and its unit whenever you reference a sensor
   (e.g. "feedwater_pressure = 17.2 MPa, normal band 18.0–20.0 MPa").
2. State the source of every number implicitly via context — readings come
   from fetch_realtime_sensors, fault codes from get_fault_history,
   projections from predict_trend, and engineering explanations / IBR
   guidance / action steps from search_knowledge_base. Do not mix these up.
3. Use 🚨 only for CRITICAL severity confirmed by the data, ⚠️ for WARNING,
   ✅ for NORMAL. Do not use these markers decoratively.
4. Keep answers proportional to the question — short questions get short
   answers. A "what is the current O2 level?" should not produce six sections.
5. If tool data conflicts (e.g. sensor reads NORMAL but fault history shows
   a recent CRITICAL alarm), call out the conflict explicitly rather than
   picking one.
6. Prefer plain text and short bullets. Avoid markdown tables unless the
   user asked for one.
7. If you are uncertain, say "based on the available data" or "I do not
   have data for X" — uncertainty stated is better than confidence faked."""

        # Load fine-tuned model
        self.model = GenerativeModel(
            model_name=FINE_TUNED_MODEL_ENDPOINT,
            system_instruction=self.system_instruction,
        )
        gen_kwargs = dict(
            temperature=GEMINI_TEMPERATURE,
            max_output_tokens=GEMINI_MAX_TOKENS,
            top_p=GEMINI_TOP_P,
        )
       
        self.gen_config = GenerationConfig(**gen_kwargs)

        print(f"✅ BoilerAgentOrchestrator ready — model: {FINE_TUNED_MODEL_ENDPOINT}")

    def run(self, user_question: str) -> dict:
        """
        Main entry point. Runs the full ReAct loop for one user question.

        Returns:
            {
                "answer":       str — final answer text
                "steps":        list — each tool call made with args and result
                "total_steps":  int — how many tool calls were made
                "latency_ms":   float — total time in milliseconds
                "question":     str — original question
                "timestamp":    str — ISO timestamp
            }
        """
        start_time = time.time()
        steps      = []
        step_count = 0

        # Build conversation history
        # Gemini function calling requires maintaining a full conversation
        # as a list of Content objects (user + model + tool turns)
        messages = [
            Content(role="user", parts=[Part.from_text(user_question)])
        ]

        print(f"\n{'='*60}")
        print(f"🧠 AGENT: Processing question: '{user_question}'")
        print(f"{'='*60}")

        final_answer = None

        # ReAct Loop
        while step_count < MAX_AGENT_STEPS:
            step_count += 1
            print(f"\n🔄 Step {step_count}/{MAX_AGENT_STEPS}")

            # Send current conversation to fine-tuned Gemini
            response = self.model.generate_content(
                messages,
                tools=[BOILER_AGENT_TOOLS],
                generation_config=self.gen_config,
            )

            candidate = response.candidates[0]
            content   = candidate.content

            # Surface truncation instead of silently returning a chopped answer.
            if str(candidate.finish_reason) == "MAX_TOKENS":
                print("⚠️  Answer hit MAX_TOKENS — increase GEMINI_MAX_TOKENS "
                      "or lower GEMINI_THINKING_BUDGET")

            # Check what Gemini returned
            # Case A: Gemini wants to call a tool
            tool_calls = [
                part for part in content.parts
                if getattr(part, "function_call", None) and part.function_call.name
            ]

            # Case B: Gemini returned a text answer      
            text_parts = [
                part for part in content.parts
                if hasattr(part, "text") and part.text.strip()
            ]

            # Keep any text emitted alongside a tool call as a fallback so it
            # isn't silently dropped if the loop ends without a clean answer.
            if text_parts:
                final_answer = "\n".join(p.text for p in text_parts).strip()

            if tool_calls:
                # Execute all requested tool calls
                tool_results_parts = []

                for part in tool_calls:
                    fc        = part.function_call
                    tool_name = fc.name
                    tool_args = dict(fc.args)

                    args_str = ", ".join(f"{k}={v!r}" for k, v in tool_args.items()) or "(no args)"
                    print(f"  🔧 Tool call: {tool_name}({args_str})")

                    # Execute the tool
                    tool_result = execute_tool(tool_name, tool_args)

                    preview = (
                        tool_result[:600] + f"\n... [truncated, {len(tool_result)} chars total]"
                        if len(tool_result) > 600 else tool_result
                    )

                    # Log the step
                    steps.append({
                        "step":           step_count,
                        "tool":           tool_name,
                        "args":           tool_args,
                        "result_preview": preview,
                        "result_length":  len(tool_result),
                    })

                    print(f"  📊 Result ({len(tool_result)} chars):")
                    for line in preview.splitlines()[:6]:
                        print(f"     {line}")

                    # Build tool result part for Gemini
                    tool_results_parts.append(
                        Part.from_function_response(
                            name=tool_name,
                            response={"result": tool_result},
                        )
                    )

                # Add Gemini's tool call request to history
                messages.append(Content(role="model", parts=content.parts))

                # Add tool results to history
                messages.append(Content(role="user", parts=tool_results_parts))

            elif text_parts:
                # ── Gemini gave a final text answer ──────────────
                final_answer = "\n".join(p.text for p in text_parts).strip()
                print(f"\n✅ Final answer received ({len(final_answer)} chars)")
                break

            else:
                # Unexpected — no tool call and no text
                print(f"  ⚠️  Step {step_count}: Empty response from Gemini")
                break

        # Handle max steps reached
        if final_answer is None:
            final_answer = (
                "I gathered the following data but reached the maximum reasoning steps. "
                "Here is a summary based on what I collected:\n\n"
                + "\n".join([f"Step {s['step']}: {s['tool']} → {s['result_preview']}"
                              for s in steps])
            )

        latency_ms = round((time.time() - start_time) * 1000, 1)

        print(f"⏱️  Total latency: {latency_ms}ms | Steps taken: {len(steps)}")

        return {
            "answer":      final_answer,
            "steps":       steps,
            "total_steps": len(steps),
            "latency_ms":  latency_ms,
            "question":    user_question,
            "timestamp":   datetime.now(UTC).isoformat() + "Z",
        }

    def run_stream(self, user_question: str):
        """
        Streaming version of run().
        Yields event dicts so the UI can render progress live:
          {"type": "status",     "message": "Thinking..."}
          {"type": "tool_start", "step": int, "tool": str, "args": dict}
          {"type": "tool_end",   "step": int, "tool": str, "result_preview": str}
          {"type": "answer_chunk", "text": str}
          {"type": "done",       "steps": [...], "total_steps": int, "latency_ms": float, "answer": str}
          {"type": "error",      "message": str}
        """
        start_time = time.time()
        steps      = []
        step_count = 0

        messages = [Content(role="user", parts=[Part.from_text(user_question)])]
        final_answer_parts: list[str] = []

        yield {"type": "status", "message": "Analyzing your question..."}

        while step_count < MAX_AGENT_STEPS:
            step_count += 1

            try:
                response = self.model.generate_content(
                    messages,
                    tools=[BOILER_AGENT_TOOLS],
                    generation_config=self.gen_config,
                )
            except Exception as e:
                yield {"type": "error", "message": f"Model error: {e}"}
                return

            candidate = response.candidates[0]
            content   = candidate.content

            if str(candidate.finish_reason) == "MAX_TOKENS":
                yield {"type": "status",
                       "message": "⚠️ Answer truncated (token limit) — "
                                  "increase GEMINI_MAX_TOKENS"}

            tool_calls = [
                p for p in content.parts
                if getattr(p, "function_call", None) and p.function_call.name
            ]
            text_parts = [
                p for p in content.parts
                if hasattr(p, "text") and p.text.strip()
            ]

            if tool_calls:
                tool_results_parts = []
                for part in tool_calls:
                    fc        = part.function_call
                    tool_name = fc.name
                    tool_args = dict(fc.args)

                    yield {
                        "type": "tool_start",
                        "step": step_count,
                        "tool": tool_name,
                        "args": tool_args,
                    }

                    tool_result = execute_tool(tool_name, tool_args)
                    preview = (
                        tool_result[:600] + f"\n... [truncated, {len(tool_result)} chars total]"
                        if len(tool_result) > 600 else tool_result
                    )

                    steps.append({
                        "step":           step_count,
                        "tool":           tool_name,
                        "args":           tool_args,
                        "result_preview": preview,
                        "result_length":  len(tool_result),
                    })

                    yield {
                        "type":           "tool_end",
                        "step":           step_count,
                        "tool":           tool_name,
                        "args":           tool_args,
                        "result_preview": preview,
                        "result_length":  len(tool_result),
                    }

                    tool_results_parts.append(
                        Part.from_function_response(
                            name=tool_name,
                            response={"result": tool_result},
                        )
                    )

                messages.append(Content(role="model", parts=content.parts))
                messages.append(Content(role="user", parts=tool_results_parts))
                yield {"type": "status", "message": "Synthesizing answer..."}

            elif text_parts:
                full_text = "\n".join(p.text for p in text_parts).strip()
                final_answer_parts.append(full_text)
                # Simulate token streaming by chunking words
                buf = ""
                for i, ch in enumerate(full_text):
                    buf += ch
                    if ch == " " or ch == "\n" or len(buf) >= 6:
                        yield {"type": "answer_chunk", "text": buf}
                        buf = ""
                if buf:
                    yield {"type": "answer_chunk", "text": buf}
                break
            else:
                break

        final_answer = "".join(final_answer_parts).strip() or (
            "I reached the maximum reasoning steps without producing a final answer."
        )
        latency_ms = round((time.time() - start_time) * 1000, 1)

        yield {
            "type":        "done",
            "answer":      final_answer,
            "steps":       steps,
            "total_steps": len(steps),
            "latency_ms":  latency_ms,
            "timestamp":   datetime.now(UTC).isoformat() + "Z",
        }