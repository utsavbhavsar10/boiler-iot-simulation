"""
End-to-end test: runs orchestrator on a set of questions, evaluates each
answer with RAGAS (faithfulness + answer_relevancy) + tool_precision,
prints a summary table.

Verifies the bug fix for: "I reached the maximum reasoning steps without
producing a final answer."
"""
import os
import sys
import json
import time
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from assistant.agent.orchestrator import BoilerAgentOrchestrator
from evaluation.evaluator import BoilerEvaluator


TEST_QUESTIONS = [
    "what is the current main steam flow?",
    "Is the boiler safe right now?",
    "Why does HIGH_FLUE_TEMP happen and how do I fix it?",
    "Will any sensor breach a threshold in the next 30 minutes?",
    "Have there been any faults in the last hour?",
]


def _build_contexts(steps):
    """Tool outputs -> contexts list for RAGAS."""
    ctx = []
    for s in steps:
        r = s.get("result") or s.get("result_preview") or ""
        if r:
            ctx.append(f"[{s['tool']}] {r}")
    return ctx


def main():
    print("=" * 70)
    print("BOILER-AI: Orchestrator + RAGAS test")
    print("=" * 70)

    agent = BoilerAgentOrchestrator()
    evaluator = BoilerEvaluator()

    results = []

    for i, q in enumerate(TEST_QUESTIONS, 1):
        print(f"\n\n{'#' * 70}\n# [{i}/{len(TEST_QUESTIONS)}] Q: {q}\n{'#' * 70}")

        t0 = time.time()
        try:
            res = agent.run(q)
        except Exception as e:
            print(f"❌ orchestrator failed: {e}")
            results.append({"q": q, "answer": None, "error": str(e)})
            continue

        print(f"\n--- ANSWER ({len(res['answer'])} chars) ---")
        print(res["answer"][:600] + ("..." if len(res["answer"]) > 600 else ""))

        # Detect the bug: empty / fallback answer
        bug_phrases = [
            "reached the maximum reasoning steps",
            "without producing a final answer",
        ]
        bug_hit = any(p in res["answer"] for p in bug_phrases)
        if bug_hit:
            print("⚠️  BUG STILL PRESENT — fallback message returned.")
        else:
            print("✅ Real answer produced.")

        steps = res["steps"]
        contexts = _build_contexts(steps) or ["(no tool context)"]
        tools_called = [s["tool"] for s in steps]

        try:
            scores = evaluator.evaluate_answer(
                question=q,
                answer=res["answer"],
                contexts=contexts,
                latency_ms=res["latency_ms"],
                steps_taken=res["total_steps"],
                tools_called=tools_called,
                had_tool_call=len(steps) > 0,
            )
        except Exception as e:
            print(f"❌ RAGAS eval failed: {e}")
            scores = {"faithfulness": None, "answer_relevancy": None,
                      "tool_precision": None, "overall_quality": None,
                      "eval_status": f"error: {e}"}

        results.append({
            "q": q,
            "answer_len": len(res["answer"]),
            "bug_hit": bug_hit,
            "tools": tools_called,
            "latency_ms": res["latency_ms"],
            "steps": res["total_steps"],
            "faithfulness": scores.get("faithfulness"),
            "answer_relevancy": scores.get("answer_relevancy"),
            "tool_precision": scores.get("tool_precision"),
            "overall_quality": scores.get("overall_quality"),
            "eval_status": scores.get("eval_status"),
        })

    # Summary table
    print("\n\n" + "=" * 110)
    print("RAGAS SUMMARY")
    print("=" * 110)
    print(f"{'#':<3} {'Bug':<5} {'Faith':<7} {'Relev':<7} {'ToolP':<7} "
          f"{'Overall':<8} {'Steps':<6} {'Lat(ms)':<9} Q")
    print("-" * 110)
    for i, r in enumerate(results, 1):
        f = r.get("faithfulness")
        rel = r.get("answer_relevancy")
        tp = r.get("tool_precision")
        ov = r.get("overall_quality")
        bug = "YES" if r.get("bug_hit") else "no"
        print(
            f"{i:<3} {bug:<5} "
            f"{('-' if f is None else f'{f:.3f}'):<7} "
            f"{('-' if rel is None else f'{rel:.3f}'):<7} "
            f"{('-' if tp is None else f'{tp:.3f}'):<7} "
            f"{('-' if ov is None else f'{ov:.3f}'):<8} "
            f"{r.get('steps', '-'): <6} "
            f"{r.get('latency_ms', '-'): <9} "
            f"{r['q'][:55]}"
        )

    # Aggregate
    fa = [r["faithfulness"] for r in results if r.get("faithfulness") is not None]
    re_ = [r["answer_relevancy"] for r in results if r.get("answer_relevancy") is not None]
    tp = [r["tool_precision"] for r in results if r.get("tool_precision") is not None]
    bugs = sum(1 for r in results if r.get("bug_hit"))

    print("-" * 110)
    print(f"Mean faithfulness    : {sum(fa)/len(fa):.3f}" if fa else "Mean faithfulness    : n/a")
    print(f"Mean answer_relevancy: {sum(re_)/len(re_):.3f}" if re_ else "Mean answer_relevancy: n/a")
    print(f"Mean tool_precision  : {sum(tp)/len(tp):.3f}" if tp else "Mean tool_precision  : n/a")
    print(f"Bug fallback hits    : {bugs}/{len(results)}")
    print("=" * 110)

    with open("test_ragas_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nResults saved → test_ragas_results.json")


if __name__ == "__main__":
    main()
