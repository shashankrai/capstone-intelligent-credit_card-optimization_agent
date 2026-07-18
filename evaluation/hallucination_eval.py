"""Answer-faithfulness / hallucination evaluation (§15 C).

Runs sample queries through the agent, then uses Claude as a judge to check whether the
answer is fully supported by the retrieved evidence + calculator results (no invented
rates, cards, partners, or numbers). Requires ANTHROPIC_API_KEY + seeded DB.

Usage:  python evaluation/hallucination_eval.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import llm  # noqa: E402
from agents.graph import run_agent  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "sample_queries.csv"

JUDGE_SYSTEM = """You are a strict faithfulness judge for a credit-card rewards assistant.
Given the retrieved evidence, the calculator results, and the assistant's answer, decide whether
EVERY factual claim/number in the answer is supported by the evidence or calculator results.
Flag any invented reward rate, card, partner, cap, or number not present in the inputs."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "faithful": {"type": "boolean"},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["faithful", "reason"],
    "additionalProperties": False,
}


def evaluate() -> dict:
    if not config.llm_ready():
        print(f"LLM not configured ({config.LLM_MODEL}) — cannot run hallucination eval (LLM required).")
        sys.exit(1)

    queries = [row["query"] for row in csv.DictReader(SAMPLES.open())]
    faithful = 0
    print(f"Faithfulness eval over {len(queries)} queries\n")

    for q in queries:
        r = run_agent(q, log=False)
        if r.get("interrupted"):  # skip HITL-paused ones for the automated judge
            print(f"  [skip] (interrupted/clarify) {q[:60]}")
            continue
        evidence = [c["chunk_text"] for c in r.get("retrieved_chunks", [])]
        payload = (
            f"EVIDENCE:\n{json.dumps(evidence)[:6000]}\n\n"
            f"CALCULATOR RESULTS:\n{json.dumps(r.get('card_totals', []) + r.get('transfer_options', []), default=str)}\n\n"
            f"ANSWER:\n{r.get('final_answer', '')}"
        )
        verdict, _ = llm.complete_json(JUDGE_SYSTEM, payload, JUDGE_SCHEMA)
        ok = verdict.get("faithful", False)
        faithful += int(ok)
        print(f"  [{'OK ' if ok else 'HALL'}] {q[:60]}  {verdict.get('reason','')[:80]}")

    print(f"\nFaithful: {faithful}/{len(queries)}")
    return {"faithful": faithful, "total": len(queries)}


if __name__ == "__main__":
    evaluate()
