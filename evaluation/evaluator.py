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

from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy
from datasets import Dataset

from langchain_google_vertexai import ChatVertexAI
from langchain_openai import OpenAIEmbeddings

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
                model_name="gemini-2.5-flash",  # base Gemini judge via Vertex AI
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
            contexts:str ,# retrieved knowledge + tool outputs used to generate the answer
            latency_ms:float ,# how long the agent took to respond
            steps_taken:int ,# how many tool calls the agent made
            tools_called:list, # which tools the agent called
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

        faithfulness_score = 0.0
        relevancy_score    = 0.0

        try:
            result = evaluate(
                dataset = eval_dataset,
                metrics = [faithfulness, answer_relevancy],
                llm     = self.judge,
                embeddings = self.embeddings,
                raise_exceptions = False 
            )
            df = result.to_pandas()  #Per row: question, answer, contexts, faithfulness, answer_relevancy

            # Extract scores safely (they could be NaN if evaluation failed)
            raw_faith  = df["faithfulness"].iloc[0]
            raw_relev  = df["answer_relevancy"].iloc[0]

            faithfulness_score = round(float(raw_faith)  if raw_faith  == raw_faith  else 0.0, 3)
            relevancy_score    = round(float(raw_relev)  if raw_relev  == raw_relev  else 0.0, 3)
            print(f"   faithfulness:     {faithfulness_score}")
            print(f"   answer_relevancy: {relevancy_score}")
       
        except Exception as e:
            print(f"   ⚠️  RAGAS evaluation error: {e}")
            print(f"   Using default scores (0.0) for this query")

        # ── Metric 3: Tool Precision ──────────────────────────────────────
        tool_precision = calculate_tool_precision(tools_called, question)
        print(f"   tool_precision:   {tool_precision}")

        # Overall quality 
        # Faithfulness and relevancy are most
        # Important (0.4 each)
        # Tool precision is also important (0.2)
        overall_quality = round(
            (faithfulness_score * 0.4) + #Heuristic  weights
            (relevancy_score    * 0.4) +
            (tool_precision     * 0.2),
            3
        )
        print(f"   overall_quality:  {overall_quality}")
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
            "tools_used":        ",".join(tools_called),
            "timestamp":         datetime.now(UTC),
        }

        # Log scores to InfluxDB
        self._log_to_influx(question, scores)

        return scores

    def _log_to_influx(self, question:str, scores:dict):
        """
        Write evaluation scores to InfluxDB measurement: chatbot_evaluation
        These are automatically visible in Grafana.
        """
        try:
            point = (
                Point("chatbot_evaluation")
                # Tags (indexed, used for filtering in Grafana)
                .tag("question_preview", question[:60])

                # Fields (the actual numbers)
                .field("faithfulness",     scores["faithfulness"])
                .field("answer_relevancy", scores["answer_relevancy"])
                .field("tool_precision",   scores["tool_precision"])
                .field("overall_quality",  scores["overall_quality"])
                .field("latency_ms",       scores["latency_ms"])
                .field("steps_taken",      float(scores["steps_taken"]))
                .field("tools_used",       scores["tools_used"])

                .time(scores["timestamp"])
            )

            _write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
            print(f"   ✅ Scores logged to InfluxDB")

        except Exception as e:
            # Evaluation logging failure should never crash the API
            print(f"   ⚠️  Failed to log to InfluxDB: {e}")
            print(f"   Scores: {scores}")