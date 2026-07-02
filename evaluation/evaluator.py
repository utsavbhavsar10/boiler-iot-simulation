"""
evaluation/evaluator.py

Measures quality of every Agentic RAG answer using:
  1. RAGAS faithfulness    — no hallucination
  2. RAGAS answer_relevancy — answers the actual question
  3. Custom tool_precision  — called the right tools
  4. Latency measurement    — response speed
  5. Steps tracking         — how many tool calls were needed

All scores are stored in InfluxDB automatically.
View scores in Grafana using the chatbot_evaluation measurement.

Note: RAGAS uses OpenAI embeddings for answer_relevancy.
"""

import warnings
# Suppress LangChain's false deprecation warning for ChatVertexAI —
# langchain-google-vertexai IS the maintained package for Vertex AI.
# Also suppress vertexai SDK UserWarning about genai deprecation.
warnings.filterwarnings("ignore", message=".*ChatVertexAI.*")
warnings.filterwarnings("ignore", message=".*deprecated.*", module="vertexai.*")

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

from ragas import evaluate
from ragas.run_config import RunConfig
from ragas.metrics import faithfulness, answer_relevancy
from datasets import Dataset

from langchain_google_vertexai import ChatVertexAI
from langchain_openai import OpenAIEmbeddings

try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass


# Dedicated single-thread executor + persistent asyncio loop.
# RAGAS spins async tasks internally; ChatVertexAI's gRPC channel binds to
# the first loop it sees. Pinning every evaluate() call to one thread with
# one long-lived loop prevents "Event loop is closed" / "_interceptors_task"
# errors on the 2nd+ question.
_eval_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ragas-eval")
_eval_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _ensure_loop():
    global _eval_loop
    with _loop_lock:
        if _eval_loop is None or _eval_loop.is_closed():
            _eval_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_eval_loop)
            try:
                nest_asyncio.apply(_eval_loop)
            except Exception:
                pass
    return _eval_loop


def _run_ragas(dataset, metrics, llm, embeddings):
    """Runs in dedicated worker thread. Reuses one persistent event loop."""
    _ensure_loop()
    return evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
        raise_exceptions=False,
        run_config=RunConfig(max_workers=1, timeout=180),
    )

from influxdb_client import InfluxDBClient , Point
from influxdb_client.client.write_api import SYNCHRONOUS

from datetime import datetime , UTC
from assistant.config import (
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    GCP_PROJECT_ID, GCP_REGION,
    EMBEDDING_MODEL,
)

# InfluxDB Write client
_influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
_write_api = _influx_client.write_api(write_options=SYNCHRONOUS)

# Expected tools per question type (for tool_precision metric)
# Maps keywords found in questions to tools that SHOULD be called.
# Used to calculate tool_precision score.

EXPECTED_TOOLS_MAP = {
    "fetch_realtime_sensors": [
        "current", "now", "right now", "safe", "reading", "value",
        "temperature", "pressure", "status", "level", "is it",
        "how much", "what is the",
    ],
    "search_knowledge_base": [
        "why", "cause", "reason", "explain", "what is", "how to fix",
        "how do i", "what does", "fault", "guide", "what happens",
        "dangerous", "mean", "definition",
    ],
    "get_fault_history": [
        "recent", "history", "occurred", "happened", "last hour",
        "last 24", "yesterday", "fault log", "events", "before",
        "when did", "how many times",
    ],
    "predict_trend": [
        "predict", "trend", "will it", "going to", "rising",
        "falling", "how long", "when will", "future", "increase",
        "get worse", "before it reaches",
    ],
    # Phase 6 — Chronos probabilistic intent keywords
    "get_chronos_forecast": [
        "will there be a fault", "about to fail", "is anything about to",
        "risk in the next", "probability", "anomaly", "unusual",
        "confidence", "forecast all", "scan all sensors", "how long until",
        "overheat", "breach in", "minutes until", "upcoming fault",
    ],
}


def get_expected_tools(question: str) -> list:
    """"
    Determine which tools should have been called based  
    on question keywords.
    Returns a list of expected tools names.
    """
    question_lower = question.lower()
    expected = []
    for tool , keywords in EXPECTED_TOOLS_MAP.items():
        if any(kw in question_lower for kw in keywords):
            expected.append(tool)
    return expected if expected else ["fetch_realtime_sensors"]  # default to this if no keywords found

def calculate_tool_precision(tools_called: list , question:str) -> float:
    """
    Calculates what fraction of expected tools were actually called.

    Formula: tools correctly called / total expected tools

    Examples:
      Expected: [fetch_realtime, search_knowledge]
      Called:   [fetch_realtime, search_knowledge]
      Score:    2/2 = 1.0

      Expected: [fetch_realtime, search_knowledge, get_fault_history]
      Called:   [fetch_realtime, search_knowledge]
      Score:    2/3 = 0.67

      Expected: [predict_trend, fetch_realtime]
      Called:   [fetch_realtime]
      Score:    1/2 = 0.5
    """
    expected = get_expected_tools(question)
    if not expected:
        return 1.0  # If no tools expected, consider it perfect precision
    correctly_called = set(tools_called) & set(expected)
    precision = len(correctly_called) / len(expected)
    return round(precision, 3)

class BoilerEvaluator:
    def __init__(self):
        """
        Initialise the evaluation engine.
        Uses base Gemini as the judge LLM and OpenAI embeddings
        for RAGAS answer_relevancy calculation.
        """
        print("Loading evaluation engine...")

        # Judge LLM — base Gemini for evaluation via Vertex AI.
        # Suppressed: LangChain incorrectly marks ChatVertexAI as deprecated;
        # langchain-google-vertexai is the correct maintained package for Vertex AI.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.judge = ChatVertexAI(
                model_name="gemini-2.5-pro",  # Pro judge — better paraphrase support recognition
                project=GCP_PROJECT_ID,
                location=GCP_REGION,
                temperature=0,    # deterministic evaluation
            )

        # Embedding model for answer_relevancy calculation
        # RAGAS uses embeddings to compare question and answer semantically.
        # Using OpenAI embeddings  needed.
        self.embeddings = OpenAIEmbeddings(
            model=EMBEDDING_MODEL
        )

        print("✅ Evaluation engine ready")
    
    def evaluate_answer(
            self, question:str , # user original question
            answer:str ,# chatbot response
            contexts:list ,# retrieved knowledge + tool outputs used to generate the answer
            latency_ms:float ,# how long the agent took to respond
            steps_taken:int ,# how many tool calls the agent made
            tools_called:list, # which tools the agent called
            had_tool_call:bool = True, # was a tool actually called for this question
        ) -> dict:

        """
        Run all evaluation metrics on one question-answer pair.

        This function is called ONCE after every /chat API request.
        It runs 3 metrics, calculates scores, logs to InfluxDB, and returns scores.

        Args:
            question: The user's original question text
            answer: The final answer text from the agent
            contexts: List of strings — each string is a tool result
                      (sensor data, knowledge base docs, fault history, etc.)
            latency_ms: Total time from question to answer in milliseconds
            steps_taken: Total number of tool calls made in this interaction
            tools_actually_called: Names of tools called (e.g. ["fetch_realtime_sensors", "search_knowledge_base"])

        Returns:
            Dict with all scores including faithfulness, answer_relevancy,
            tool_precision, overall_quality, and latency_ms
        """
        print(f"\n📊 Evaluating answer for: '{question[:60]}...'")

        # ── Metric 1 + 2: RAGAS Faithfulness + Answer Relevancy ──────────
        # RAGAS needs a specific format: Dataset with question, answer, contexts
        # contexts must be a list of strings (not a single string)
        eval_dataset = Dataset.from_dict({
            "question": [question],
            "answer":   [answer],
            "contexts": [contexts],   # list of strings, wrapped in outer list
        }) 

        faithfulness_score = None
        relevancy_score    = None
        eval_status        = "ok"

        try:
            future = _eval_executor.submit(
                _run_ragas,
                eval_dataset,
                [faithfulness, answer_relevancy],
                self.judge,
                self.embeddings,
            )
            result = future.result(timeout=240)
            df = result.to_pandas()  #Per row: question, answer, contexts, faithfulness, answer_relevancy

            raw_faith  = df["faithfulness"].iloc[0]
            raw_relev  = df["answer_relevancy"].iloc[0]

            # NaN check (NaN != NaN). NaN → None (skip field), not 0.0.
            faithfulness_score = None if raw_faith != raw_faith else round(float(raw_faith), 3)
            relevancy_score    = None if raw_relev != raw_relev else round(float(raw_relev), 3)

            if faithfulness_score is None and relevancy_score is None:
                eval_status = "nan"

            print(f"   faithfulness:     {faithfulness_score}")
            print(f"   answer_relevancy: {relevancy_score}")

        except Exception as e:
            print(f"   ⚠️  RAGAS evaluation error: {e}")
            eval_status = "failed"

        # ── Metric 3: Tool Precision ──────────────────────────────────────
        tool_precision = calculate_tool_precision(tools_called, question)
        print(f"   tool_precision:   {tool_precision}")

        # Overall quality — only computable when both RAGAS metrics succeeded.
        if faithfulness_score is not None and relevancy_score is not None:
            overall_quality = round(
                (faithfulness_score * 0.4) +
                (relevancy_score    * 0.4) +
                (tool_precision     * 0.2),
                3
            )
        else:
            overall_quality = None

        print(f"   overall_quality:  {overall_quality}")
        print(f"   eval_status:      {eval_status}")
        print(f"   latency_ms:       {latency_ms}")
        print(f"   steps_taken:      {steps_taken}")

        # All Scores
        scores = {
            "faithfulness":      faithfulness_score,
            "answer_relevancy":  relevancy_score,
            "tool_precision":    tool_precision,
            "overall_quality":   overall_quality,
            "latency_ms":        latency_ms,
            "steps_taken":       steps_taken,
            "tools_used":        ",".join(tools_called) if tools_called else "none",
            "eval_status":       eval_status,
            "had_tool_call":     had_tool_call,
            "timestamp":         datetime.now(UTC),
        }

        # Log scores to InfluxDB
        self._log_to_influx(question, scores)

        return scores

    def _log_to_influx(self, question:str, scores:dict):
        """
        Write evaluation scores to InfluxDB measurement: chatbot_evaluation
        These are automatically visible in Grafana.

        NaN/None metric values are SKIPPED, not written as 0.0 — so dashboards
        reflect real failures vs real low scores. Use the `eval_status` tag
        to filter ok vs nan vs failed rows.
        """
        try:
            point = (
                Point("chatbot_evaluation")
                # Tags (indexed, used for filtering in Grafana)
                .tag("question_preview", question[:60])
                .tag("eval_status",      scores.get("eval_status", "ok"))
                .tag("had_tool_call",    "true" if scores.get("had_tool_call") else "false")
            )

            # Only write metric fields that successfully evaluated.
            for key in ("faithfulness", "answer_relevancy", "tool_precision", "overall_quality"):
                val = scores.get(key)
                if val is not None:
                    point = point.field(key, float(val))

            # Always-present operational fields.
            point = (
                point
                .field("latency_ms",  float(scores["latency_ms"]))
                .field("steps_taken", float(scores["steps_taken"]))
                .field("tools_used",  scores["tools_used"])
                .time(scores["timestamp"])
            )

            _write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
            print(f"   ✅ Scores logged to InfluxDB (status={scores.get('eval_status')})")

        except Exception as e:
            # Evaluation logging failure should never crash the API
            print(f"   ⚠️  Failed to log to InfluxDB: {e}")
            print(f"   Scores: {scores}")