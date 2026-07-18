"""Evaluation harness — runs golden test cases through the agent.

Checks intent accuracy and (when specified) whether the recommended card is in the
allowed set. Requires ANTHROPIC_API_KEY + a seeded database.

Usage:  python evaluation/evaluate.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from agents.graph import run_agent  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden_answers.csv"


def main() -> None:
    if not config.llm_ready():
        print(f"LLM not configured ({config.LLM_MODEL}) — cannot run evaluation (LLM steps required).")
        sys.exit(1)

    rows = list(csv.DictReader(GOLDEN.open()))
    passed = 0
    print(f"Running {len(rows)} golden cases...\n")

    for row in rows:
        result = run_agent(row["query"], log=False)
        intent = result.get("intent", "")
        rec = result.get("recommended_card")
        intent_ok = intent == row["expected_intent"]

        allowed = [c.strip() for c in (row.get("allowed_cards") or "").split("|") if c.strip()]
        card_ok = (not allowed) or (rec in allowed) or result.get("needs_clarification") \
            or result.get("needs_approval")

        ok = intent_ok and card_ok
        passed += int(ok)
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] #{row['id']} intent={intent} (exp {row['expected_intent']}) "
              f"card={rec} {'in '+str(allowed) if allowed else ''}")
        if not ok:
            print(f"        query: {row['query']}")

    print(f"\nScore: {passed}/{len(rows)} ({100*passed/len(rows):.0f}%)")


if __name__ == "__main__":
    main()
