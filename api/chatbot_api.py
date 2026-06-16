"""
FastAPI — Boiler Agentic RAG API
Endpoints:
  POST /chat          — run agent, returns answer + steps + eval scores
  GET  /status        — live sensor snapshot
  GET  /metrics       — 24h evaluation averages from InfluxDB
  GET  /health        — service health check
"""
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import datetime , UTC
import json

from assistant.agent.orchestrator   import BoilerAgentOrchestrator
from assistant.agent.tools.realtime_tool import fetch_realtime_sensors
from assistant.agent.tools.fault_history  import get_fault_history
from influxdb_client import InfluxDBClient
from assistant.config import INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG
from evaluation.evaluator import BoilerEvaluator
app = FastAPI(
    title="Boiler Agentic RAG Chatbot",
    description="Fine-tuned Gemini 2.5 Flash + Agentic RAG for boiler/chimney monitoring",
    version="3.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialise once at startup (heavy objects)
agent     = BoilerAgentOrchestrator()
evaluator = BoilerEvaluator()

influx    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)


class ChatRequest(BaseModel):
    question:    str
    session_id:  str = "default"
    evaluate:    bool = True   # set False to skip RAGAS scoring


@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now(UTC).isoformat()}


@app.post("/chat")
def chat(request: ChatRequest):
    """
    Main chat endpoint.
    Runs the Agentic RAG loop and returns:
    - answer: final grounded response
    - steps: which tools were called and with what results
    - eval_scores: faithfulness, relevancy, tool precision, latency
    """
    #  Step 1: Run agent
    result = agent.run(request.question)

    # Step 2: Collect contexts for RAGAS
    # contexts = all tool results combined as list of strings
    # RAGAS reads these to judge whether the answer used them faithfully
    contexts = []
    tools_called = []
    for step in result["steps"]:
        contexts.append(
            f"Tool: {step['tool']}\nResult: {step['result_preview']}"
        )
        tools_called.append(step["tool"])

    # Step 3: Evaluate (if contexts exist and evaluate=True)
    eval_scores = {}
    if request.evaluate and contexts:
        eval_scores = evaluator.evaluate_answer(
            question=request.question,
            answer=result["answer"],
            contexts=contexts,
            latency_ms=result["latency_ms"],
            steps_taken=result["total_steps"],
            tools_called=tools_called,
        )

    return {
        "question":    request.question,
        "answer":      result["answer"],
        "steps":       result["steps"],
        "total_steps": result["total_steps"],
        "latency_ms":  result["latency_ms"],
        "eval_scores": eval_scores,
        "timestamp":   result["timestamp"],
    }
    

@app.post("/chat/stream")
def chat_stream(request: ChatRequest):
    """Server-Sent Events stream of agent events for live UI updates."""
    def event_gen():
        final = None
        try:
            for evt in agent.run_stream(request.question):
                if evt.get("type") == "done":
                    final = evt
                yield f"data: {json.dumps(evt)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        # After stream completes, run evaluation so chatbot_evaluation
        # is written to InfluxDB (streaming path previously skipped this).
        if request.evaluate and final and final.get("steps"):
            try:
                contexts = [
                    f"Tool: {s['tool']}\nResult: {s['result_preview']}"
                    for s in final["steps"]
                ]
                tools_called = [s["tool"] for s in final["steps"]]
                evaluator.evaluate_answer(
                    question=request.question,
                    answer=final["answer"],
                    contexts=contexts,
                    latency_ms=final["latency_ms"],
                    steps_taken=final["total_steps"],
                    tools_called=tools_called,
                )
            except Exception as e:
                print(f"⚠️  Stream eval failed: {e}")
    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/status")
def status():
    """Returns live sensor readings and recent faults."""
    return {
        "sensors":   fetch_realtime_sensors(),
        "faults":    get_fault_history(minutes=60),
        "timestamp": datetime.now(UTC).isoformat(),
    }

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data     = await websocket.receive_text()
            payload  = json.loads(data)
            question = payload.get("question", "")
            result   = agent.run(question)
            await websocket.send_json({
                "answer":      result["answer"],
                "steps":       result["steps"],
                "latency_ms":  result["latency_ms"],
                "timestamp":   result["timestamp"],
            })
    except Exception:
        pass