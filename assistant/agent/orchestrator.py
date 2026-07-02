"""
This file implements the ReAct loop:
  1. Send question + tool schemas to fine-tuned Gemini
  2. Gemini returns either: a tool_call OR a final text answer
  3. If tool_call → execute the Python function → send result back to Gemini
  4. If final answer → return it with all metadata

The fine-tuned model reasons about WHICH tools to call based on the question.
The orchestrator EXECUTES those calls and feeds results back.

Production hardening (Session 3 fixes):
  - Conversational pre-check: greetings / short messages bypass the model entirely.
  - Question-first ordering: user question comes FIRST, Chronos block appended
    at the end (capped to top-5 sensors, max 800 chars).
  - Retry on empty response: one automatic retry with stripped context
    (no Chronos block, no history) before showing an error.
  - Base-model fallback: if fine-tuned model returns empty twice, fall back to
    gemini-2.0-flash (no tools, text-only) to guarantee a response.
  - Improved synthesis prompt: structured prompt referencing the actual tool data.
  - Handles all finish_reason values (STOP, MAX_TOKENS, SAFETY, OTHER, RECITATION).
"""
import re
import vertexai
from vertexai.generative_models import (
    GenerativeModel,
    GenerationConfig,
    Content,
    Part,
)

import json
import time
from datetime import datetime, UTC

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
from assistant.agent.tools.chronos_tool   import get_chronos_forecast  # Phase 4

# ── Initialise Vertex AI
vertexai.init(project=GCP_PROJECT_ID, location=GCP_REGION)

# ── Tool dispatcher
# Maps tool name (string from Gemini) → actual Python function
TOOL_REGISTRY = {
    "fetch_realtime_sensors": fetch_realtime_sensors,
    "search_knowledge_base":  search_knowledge_base,
    "get_fault_history":      get_fault_history,
    "predict_trend":          predict_trend,          # now Chronos-powered internally
    "get_chronos_forecast":   get_chronos_forecast,   # Phase 4 — new probabilistic tool
}

# ── Fallback base model for when fine-tuned model returns empty ───────────────
# Used ONLY as a last resort — no tools, text-only synthesis from collected data.
_FALLBACK_MODEL_NAME = "gemini-2.0-flash"

# ── Conversational keyword patterns ──────────────────────────────────────────
# Short messages matching these patterns are answered directly without calling
# the fine-tuned model (which is optimised for tool-use, not greetings).
_GREETING_PATTERNS = re.compile(
    r"^\s*(hi|hello|hey|good\s+(morning|afternoon|evening|day)|howdy|"
    r"thanks|thank\s+you|thx|ty|ok|okay|got\s+it|understood|great|"
    r"cool|nice|perfect|bye|goodbye|see\s+ya|later|sure|yep|yes|no|"
    r"nope|alright|sounds\s+good)\s*[!.?]*\s*$",
    re.IGNORECASE,
)

_GREETING_RESPONSES = {
    "hi": "Hello! I'm BOILER-AI, your industrial boiler monitoring assistant. How can I help you today?",
    "hello": "Hello! I'm BOILER-AI. Ask me about sensor readings, fault diagnosis, predictions, or engineering guidance.",
    "hey": "Hey! BOILER-AI here. What would you like to know about the boiler system?",
    "thanks": "You're welcome! Let me know if you need any more help with the boiler system.",
    "thank you": "Happy to help! Feel free to ask about any sensor readings, faults, or predictions.",
    "thx": "You're welcome! Ask me anything about the boiler system.",
    "ty": "No problem! I'm here whenever you need boiler diagnostics or predictions.",
    "bye": "Goodbye! Stay safe. I'll be here whenever you need boiler monitoring support.",
    "goodbye": "Goodbye! The boiler monitoring system will keep running. Come back any time.",
    "ok": "Got it! Let me know if you need anything else.",
    "okay": "Understood. Ask me anything about the boiler, chimney, or turbine sensors.",
    "default": (
        "I'm BOILER-AI — your boiler monitoring and diagnostic assistant. "
        "You can ask me about:\n"
        "• **Live sensor readings** (current temperatures, pressures, flows)\n"
        "• **Fault diagnosis** (why is X alarming? what does fault code Y mean?)\n"
        "• **Predictions** (will any sensor breach a threshold in the next hour?)\n"
        "• **Fault history** (recent alarms, patterns, recurrence)\n"
        "• **Engineering guidance** (IBR compliance, root causes, corrective actions)"
    ),
}


def _get_greeting_response(text: str) -> str | None:
    """
    If the message is a conversational greeting/acknowledgement, return a
    canned response immediately. Returns None if the message is a real query.
    """
    stripped = text.strip()
    if not _GREETING_PATTERNS.match(stripped):
        return None
    # Match to the best canned response
    lower = stripped.lower().rstrip("!.? ")
    for key, resp in _GREETING_RESPONSES.items():
        if key != "default" and lower.startswith(key):
            return resp
    return _GREETING_RESPONSES["default"]


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


def _build_chronos_block() -> str:
    """
    Build the trimmed Chronos context block (max 5 sensors, max 800 chars).
    Returns empty string if cache is stale or empty.
    """
    from assistant.agent.chronos_service import chronos_service, chronos_cache
    if not chronos_cache:
        return ""
    latest_refresh = max(
        (fc.last_refreshed for fc in chronos_cache.values()), default=0.0
    )
    if time.time() - latest_refresh > 120:
        return ""  # cache stale — skip injection
    block = chronos_service.format_for_llm_context(
        chronos_cache, max_sensors=5, max_chars=800
    )
    return block + "\n\n"


class BoilerAgentOrchestrator:

    def __init__(self):
        # System instruction — injected once, shapes all responses
        self.system_instruction = """You are BOILER-AI, a senior industrial engineer specialising in boiler, turbine and chimney systems, grounded in Indian Boiler Regulations (IBR) standards.

═══════════════════════════════════════════════════════════════
CORE PRINCIPLE — GROUND TRUTH ONLY
═══════════════════════════════════════════════════════════════
Every factual sentence in your answer MUST paraphrase content that appears in a
tool result returned in this conversation. If the tools returned no relevant
data for a part of the question, say so plainly for that part — do NOT fall
back on training memory to fill the gap, do NOT invent sensor readings, fault
codes, timestamps, thresholds, IBR clauses, or trends, and do NOT paraphrase
"typical" values as if they were the current reading. If a tool returned an
error or empty result, report that truthfully.

OPENING SENTENCE RULE: the first sentence of every answer must directly answer
the user's question using the same key terms they used. No preambles like
"Based on the current sensor readings". Lead with the answer, then evidence.

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
  minutes, "will X exceed Y", "is it rising/falling").
- get_chronos_forecast → PROBABILISTIC FUTURE intent. Use this when the
  question asks about likelihood, uncertainty, confidence, anomaly, or
  risk ranking across sensors: "Will there be a fault?", "How long until
  overheat?", "Is anything about to fail?", "What is the risk?",
  "Scan all sensors for upcoming problems". Returns probabilistic forecast
  with confidence bands, anomaly score, and minutes-to-warning/critical.
  Prefer this over predict_trend when the question implies uncertainty
  or multi-sensor risk scan. Use predict_trend for single-sensor
  simple trend/direction questions.

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
   • "Will any sensor breach a threshold in the next 30 min?"
     → get_chronos_forecast (sensor_name='all')
   • "Is oxygen level about to fall critical?"
     → get_chronos_forecast (sensor_name='oxygen_level')
   • "Full diagnosis: status, recent history, prediction and root cause"
     → fetch_realtime_sensors + get_fault_history + get_chronos_forecast + search_knowledge_base.
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
ANSWER SHAPE — HARD LENGTH CAPS, NO TEMPLATE PADDING
═══════════════════════════════════════════════════════════════
Apply these caps strictly. Skip any section that has no tool-grounded content.

- Definition / "what is X"         → ≤4 sentences, no sections.
- Single sensor value lookup       → 1 sentence: value, unit, status, normal band.
- Yes/no question                  → answer in sentence 1, evidence in sentence 2.
- Trend / prediction               → ≤3 sentences: current value, rate, time-to-threshold.
- History summary                  → bullets only, only entries get_fault_history returned.
- Procedure / how-to               → numbered steps grounded in search_knowledge_base output.
- Full fault diagnosis             → up to 5 sections (Current Status, Diagnosis,
                                     Root Cause, Immediate Actions, Prevention).
                                     SKIP any section whose content is not in tool output.

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

        # Fallback base model — used ONLY when fine-tuned model returns empty twice.
        # No system instruction (it's a one-shot synthesis call), no tools.
        self._fallback_model = GenerativeModel(model_name=_FALLBACK_MODEL_NAME)
        self._fallback_gen_config = GenerationConfig(
            temperature=0.2,
            max_output_tokens=1024,
            top_p=0.9,
        )

        print(f"✅ BoilerAgentOrchestrator ready — model: {FINE_TUNED_MODEL_ENDPOINT}")
        print(f"   Fallback model: {_FALLBACK_MODEL_NAME}")

    def _build_history_block(self, history: list | None, summary: str | None) -> str:
        """
        Format Redis chat history + summary as a text block to prepend to the
        user turn. Prepending as text (not as multi-turn Content objects) avoids
        Gemini function-call schema mismatches from prior tool-call turns.
        """
        block = ""
        if summary:
            block += f"=== PRIOR CONVERSATION SUMMARY ===\n{summary}\n\n"
        if history:
            lines = ["=== RECENT CHAT HISTORY (oldest first) ==="]
            for m in history:
                tag = "USER" if m.get("role") == "user" else "ASSISTANT"
                lines.append(f"[{tag}] {m.get('content', '')}")
            lines.append("=== END HISTORY ===\n")
            block += "\n".join(lines) + "\n\n"
        return block

    def _build_enriched_question(
        self,
        user_question: str,
        history: list | None,
        summary: str | None,
        include_chronos: bool = True,
    ) -> str:
        """
        Build the enriched question with question FIRST, then history context,
        then the (trimmed) Chronos forecast block at the end.

        Question-first ordering ensures the fine-tuned model sees the actual
        query before any long context blocks — critical for correct tool selection.
        """
        history_block   = self._build_history_block(history, summary)
        chronos_block   = _build_chronos_block() if include_chronos else ""
        enriched        = history_block + user_question
        if chronos_block:
            enriched += "\n\n" + chronos_block
        return enriched

    def _fallback_synthesis(self, question: str, steps: list) -> str:
        """
        Last-resort answer generation using the base Gemini Flash model.
        Called when the fine-tuned model returns empty twice.
        Constructs a text-only synthesis prompt from collected tool data.
        """
        if not steps:
            return (
                "I'm sorry, I wasn't able to retrieve sensor data at this time. "
                "Please check that the backend services (InfluxDB, MQTT) are running, "
                "then try again."
            )
        tool_summary = "\n\n".join(
            f"Tool: {s['tool']}\nResult:\n{s['result_preview']}"
            for s in steps
        )
        synthesis_prompt = (
            f"You are a boiler monitoring AI assistant. "
            f"A user asked: \"{question}\"\n\n"
            f"The following tool data was collected:\n\n"
            f"{tool_summary}\n\n"
            f"Using ONLY the tool data above, write a clear, concise answer "
            f"to the user's question. Lead with the direct answer, cite sensor "
            f"values with their units and status (NORMAL/WARNING/CRITICAL). "
            f"Do not invent data not present in the tool results. "
            f"Maximum 150 words."
        )
        try:
            resp = self._fallback_model.generate_content(
                [Content(role="user", parts=[Part.from_text(synthesis_prompt)])],
                generation_config=self._fallback_gen_config,
            )
            text = "\n".join(
                p.text for p in resp.candidates[0].content.parts
                if hasattr(p, "text") and p.text.strip()
            ).strip()
            if text:
                print(f"   ✅ Fallback model synthesis succeeded ({len(text)} chars)")
                return text
        except Exception as fb_err:
            print(f"   ⚠️  Fallback model error: {fb_err}")

        # If even fallback fails, surface the raw tool data
        return (
            "Based on the collected sensor data:\n\n"
            + "\n\n".join(
                f"**{s['tool']}**: {s['result_preview'][:300]}"
                for s in steps
            )
        )

    def _improved_synthesis_prompt(self, question: str, steps: list) -> str:
        """Build an improved synthesis prompt that references specific tool data."""
        tool_refs = ", ".join(s["tool"] for s in steps)
        return (
            f"The user asked: \"{question}\"\n\n"
            f"Tools called: {tool_refs}. "
            f"Their results are in the conversation above.\n\n"
            f"Write the final answer now using ONLY those tool results. "
            f"Lead with a direct answer to the question. "
            f"Cite sensor values with units and status. "
            f"Do not call any more tools. Be concise — maximum 200 words."
        )

    def run(self, user_question: str, history: list | None = None, summary: str | None = None) -> dict:
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

        print(f"\n{'='*60}")
        print(f"🧠 AGENT: Processing question: '{user_question}'")
        print(f"{'='*60}")

        # ── Pre-check: handle conversational greetings without model call ─────
        greeting_resp = _get_greeting_response(user_question)
        if greeting_resp:
            print("   💬 Conversational message detected — skipping model call.")
            latency_ms = round((time.time() - start_time) * 1000, 1)
            return {
                "answer":      greeting_resp,
                "steps":       [],
                "total_steps": 0,
                "latency_ms":  latency_ms,
                "question":    user_question,
                "timestamp":   datetime.now(UTC).isoformat() + "Z",
            }

        # ── Build enriched question (question first, Chronos block at end) ───
        enriched_question = self._build_enriched_question(
            user_question, history, summary, include_chronos=True
        )
        messages = [Content(role="user", parts=[Part.from_text(enriched_question)])]
        final_answer = None
        empty_response_count = 0  # track consecutive empty responses for retry logic

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
            fr        = str(candidate.finish_reason)

            # Surface truncation warning
            if fr == "MAX_TOKENS":
                print("⚠️  Answer hit MAX_TOKENS — consider increasing GEMINI_MAX_TOKENS")

            # Check what Gemini returned
            tool_calls = [
                part for part in content.parts
                if getattr(part, "function_call", None) and part.function_call.name
            ]
            text_parts = [
                part for part in content.parts
                if hasattr(part, "text") and part.text.strip()
            ]

            # Keep any text emitted alongside a tool call as fallback
            if text_parts:
                final_answer = "\n".join(p.text for p in text_parts).strip()

            if tool_calls:
                empty_response_count = 0  # reset on successful response
                tool_results_parts = []

                for part in tool_calls:
                    fc        = part.function_call
                    tool_name = fc.name
                    tool_args = dict(fc.args)

                    args_str = ", ".join(f"{k}={v!r}" for k, v in tool_args.items()) or "(no args)"
                    print(f"  🔧 Tool call: {tool_name}({args_str})")

                    tool_result = execute_tool(tool_name, tool_args)
                    preview = (
                        tool_result[:600] + f"\n... [truncated, {len(tool_result)} chars total]"
                        if len(tool_result) > 600 else tool_result
                    )

                    steps.append({
                        "step":           step_count,
                        "tool":           tool_name,
                        "args":           tool_args,
                        "result":         tool_result,
                        "result_preview": preview,
                        "result_length":  len(tool_result),
                    })

                    print(f"  📊 Result ({len(tool_result)} chars):")
                    for line in preview.splitlines()[:6]:
                        print(f"     {line}")

                    tool_results_parts.append(
                        Part.from_function_response(
                            name=tool_name,
                            response={"result": tool_result},
                        )
                    )

                messages.append(Content(role="model", parts=content.parts))
                messages.append(Content(role="user", parts=tool_results_parts))

            elif text_parts:
                # Gemini gave a final text answer
                final_answer = "\n".join(p.text for p in text_parts).strip()
                print(f"\n✅ Final answer received ({len(final_answer)} chars)")
                break

            else:
                # Empty response — no tool call and no text.
                empty_response_count += 1
                safety = getattr(candidate, "safety_ratings", None)
                print(
                    f"  ⚠️  Step {step_count}: Empty response | "
                    f"finish_reason={fr} | parts={len(content.parts)} | "
                    f"safety={safety} | empty_count={empty_response_count}"
                )

                if fr in ("SAFETY", "RECITATION"):
                    # Safety block — don't retry; fall through to synthesis/fallback
                    print(f"     Blocked by safety filter ({fr}) — skipping retry.")
                    break

                if empty_response_count == 1 and steps:
                    # First empty — try a synthesis turn (no tools, structured prompt)
                    print("     → Attempting structured synthesis (no tools)...")
                    try:
                        messages.append(Content(role="user", parts=[Part.from_text(
                            self._improved_synthesis_prompt(user_question, steps)
                        )]))
                        synth_cfg = GenerationConfig(
                            temperature=GEMINI_TEMPERATURE,
                            max_output_tokens=2048,
                            top_p=GEMINI_TOP_P,
                        )
                        synth = self.model.generate_content(
                            messages, generation_config=synth_cfg
                        )
                        synth_text = "\n".join(
                            p.text for p in synth.candidates[0].content.parts
                            if hasattr(p, "text") and p.text.strip()
                        ).strip()
                        if synth_text:
                            final_answer = synth_text
                            print(f"     ✅ Synthesis succeeded ({len(synth_text)} chars)")
                            break
                        else:
                            print("     ⚠️  Synthesis also empty — will use fallback model.")
                    except Exception as synth_err:
                        print(f"     ⚠️  Synthesis error: {synth_err}")
                    break

                elif empty_response_count == 1 and not steps:
                    # No tools fired and empty response — retry with stripped context
                    print("     → Retrying with stripped context (no Chronos, no history)...")
                    stripped = self._build_enriched_question(
                        user_question, None, None, include_chronos=False
                    )
                    messages = [Content(role="user", parts=[Part.from_text(stripped)])]
                    step_count -= 1  # don't count retry as a step
                    continue

                else:
                    # Second empty — give up and go to fallback
                    print("     → Second empty response — breaking to fallback.")
                    break

        # ── Forced synthesis: tools ran but no final text yet ─────────────────
        if final_answer is None and steps:
            print("\n🔄 Forced synthesis — tools ran but no final answer produced.")
            try:
                messages.append(Content(role="user", parts=[Part.from_text(
                    self._improved_synthesis_prompt(user_question, steps)
                )]))
                synth_cfg = GenerationConfig(
                    temperature=GEMINI_TEMPERATURE,
                    max_output_tokens=4096,
                    top_p=GEMINI_TOP_P,
                )
                synth = self.model.generate_content(
                    messages, generation_config=synth_cfg
                )
                synth_text = "\n".join(
                    p.text for p in synth.candidates[0].content.parts
                    if hasattr(p, "text") and p.text.strip()
                ).strip()
                if synth_text:
                    final_answer = synth_text
                    print(f"   ✅ Forced synthesis succeeded ({len(synth_text)} chars)")
            except Exception as e:
                print(f"⚠️  Forced synthesis failed: {e}")

        # ── Base-model fallback: fine-tuned model returned nothing at all ─────
        if final_answer is None:
            print("\n🔄 Base-model fallback triggered.")
            final_answer = self._fallback_synthesis(user_question, steps)

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

    def run_stream(self, user_question: str, history: list | None = None, summary: str | None = None):
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

        # ── Pre-check: handle conversational greetings without model call ─────
        greeting_resp = _get_greeting_response(user_question)
        if greeting_resp:
            yield {"type": "status", "message": "BOILER-AI ready."}
            for ch_buf in [greeting_resp[i:i+6] for i in range(0, len(greeting_resp), 6)]:
                yield {"type": "answer_chunk", "text": ch_buf}
            yield {
                "type":        "done",
                "answer":      greeting_resp,
                "steps":       [],
                "total_steps": 0,
                "latency_ms":  round((time.time() - start_time) * 1000, 1),
                "timestamp":   datetime.now(UTC).isoformat() + "Z",
            }
            return

        # ── Build enriched question (question first, Chronos block at end) ───
        enriched_question = self._build_enriched_question(
            user_question, history, summary, include_chronos=True
        )
        messages = [Content(role="user", parts=[Part.from_text(enriched_question)])]
        final_answer_parts: list[str] = []
        empty_response_count = 0

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
            fr        = str(candidate.finish_reason)

            if fr == "MAX_TOKENS":
                yield {"type": "status", "message": "⚠️ Answer truncated (token limit)."}

            tool_calls = [
                p for p in content.parts
                if getattr(p, "function_call", None) and p.function_call.name
            ]
            text_parts = [
                p for p in content.parts
                if hasattr(p, "text") and p.text.strip()
            ]

            # Capture text alongside tool calls as fallback
            if text_parts and tool_calls:
                inline_text = "\n".join(p.text for p in text_parts).strip()
                if inline_text:
                    final_answer_parts.append(inline_text)

            if tool_calls:
                empty_response_count = 0
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
                        "result":         tool_result,
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
                # Stream the answer in small chunks
                buf = ""
                for ch in full_text:
                    buf += ch
                    if ch == " " or ch == "\n" or len(buf) >= 6:
                        yield {"type": "answer_chunk", "text": buf}
                        buf = ""
                if buf:
                    yield {"type": "answer_chunk", "text": buf}
                break

            else:
                # Empty response
                empty_response_count += 1
                safety = getattr(candidate, "safety_ratings", None)
                print(
                    f"  ⚠️  Step {step_count}: empty response | "
                    f"finish_reason={fr} | parts={len(content.parts)} | "
                    f"safety={safety} | empty_count={empty_response_count}"
                )

                if fr in ("SAFETY", "RECITATION"):
                    yield {"type": "status", "message": f"⚠️ Content blocked by safety filter."}
                    break

                if empty_response_count == 1 and steps:
                    # Try structured synthesis
                    yield {"type": "status", "message": "Refining answer..."}
                    try:
                        messages.append(Content(role="user", parts=[Part.from_text(
                            self._improved_synthesis_prompt(user_question, steps)
                        )]))
                        synth_cfg = GenerationConfig(
                            temperature=GEMINI_TEMPERATURE,
                            max_output_tokens=2048,
                            top_p=GEMINI_TOP_P,
                        )
                        synth = self.model.generate_content(
                            messages, generation_config=synth_cfg
                        )
                        synth_text = "\n".join(
                            p.text for p in synth.candidates[0].content.parts
                            if hasattr(p, "text") and p.text.strip()
                        ).strip()
                        if synth_text:
                            final_answer_parts.append(synth_text)
                            for ch_buf in [synth_text[i:i+6] for i in range(0, len(synth_text), 6)]:
                                yield {"type": "answer_chunk", "text": ch_buf}
                            break
                    except Exception as se:
                        print(f"     ⚠️  Synthesis error in stream: {se}")
                    break

                elif empty_response_count == 1 and not steps:
                    # No tools fired — retry with stripped context
                    yield {"type": "status", "message": "Retrying with simplified context..."}
                    stripped = self._build_enriched_question(
                        user_question, None, None, include_chronos=False
                    )
                    messages = [Content(role="user", parts=[Part.from_text(stripped)])]
                    step_count -= 1
                    continue

                else:
                    yield {"type": "status", "message": "⚠️ Model returned empty response. Using fallback..."}
                    break

        # ── Forced synthesis via fine-tuned model ─────────────────────────────
        if not final_answer_parts and steps:
            yield {"type": "status", "message": "Preparing final answer..."}
            synth_text = ""
            try:
                messages.append(Content(role="user", parts=[Part.from_text(
                    self._improved_synthesis_prompt(user_question, steps)
                )]))
                synth_cfg = GenerationConfig(
                    temperature=GEMINI_TEMPERATURE,
                    max_output_tokens=4096,
                    top_p=GEMINI_TOP_P,
                )
                synth = self.model.generate_content(
                    messages, generation_config=synth_cfg
                )
                synth_text = "\n".join(
                    p.text for p in synth.candidates[0].content.parts
                    if hasattr(p, "text") and p.text.strip()
                ).strip()
            except Exception as e:
                yield {"type": "status", "message": f"Synthesis error: {e}"}

            if synth_text:
                final_answer_parts.append(synth_text)
                for ch_buf in [synth_text[i:i+6] for i in range(0, len(synth_text), 6)]:
                    yield {"type": "answer_chunk", "text": ch_buf}
            else:
                # ── Base-model fallback ───────────────────────────────────────
                yield {"type": "status", "message": "Using base model fallback..."}
                fallback_text = self._fallback_synthesis(user_question, steps)
                final_answer_parts.append(fallback_text)
                for ch_buf in [fallback_text[i:i+6] for i in range(0, len(fallback_text), 6)]:
                    yield {"type": "answer_chunk", "text": ch_buf}

        # ── If still nothing (no tools fired, no text) — base model fallback ─
        if not final_answer_parts:
            yield {"type": "status", "message": "Using base model fallback..."}
            fallback_text = self._fallback_synthesis(user_question, steps)
            final_answer_parts.append(fallback_text)
            for ch_buf in [fallback_text[i:i+6] for i in range(0, len(fallback_text), 6)]:
                yield {"type": "answer_chunk", "text": ch_buf}

        final_answer = "".join(final_answer_parts).strip()
        latency_ms = round((time.time() - start_time) * 1000, 1)
        yield {
            "type":        "done",
            "answer":      final_answer,
            "steps":       steps,
            "total_steps": len(steps),
            "latency_ms":  latency_ms,
            "timestamp":   datetime.now(UTC).isoformat() + "Z",
        }