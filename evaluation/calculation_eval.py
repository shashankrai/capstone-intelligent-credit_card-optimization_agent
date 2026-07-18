"""Calculation evaluation (§15 B) — asserts the calculator matches expected values.

Deterministic: no DB, no API key.

Usage:  python evaluation/calculation_eval.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.calculator import compute_reward  # noqa: E402

CASES = Path(__file__).resolve().parent / "calculation_cases.csv"
TOL = 0.01


def evaluate() -> dict:
    rows = list(csv.DictReader(CASES.open()))
    passed = 0
    print(f"Calculation eval over {len(rows)} cases\n")
    for i, row in enumerate(rows, 1):
        cap = float(row["monthly_cap"]) if row["monthly_cap"] else None
        r = compute_reward(
            spend=float(row["spend"]),
            reward_rate=float(row["reward_rate"]),
            reward_per_amount=float(row["reward_per_amount"]),
            point_value=float(row["point_value"]),
            monthly_cap=cap,
            exclusion=bool(int(row["exclusion"])),
        )
        exp_val = float(row["expected_value"])
        exp_pct = float(row["expected_return_pct"])
        ok = abs(r["reward_value"] - exp_val) <= TOL and abs(r["effective_return_pct"] - exp_pct) <= 0.1
        passed += int(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] #{i} value={r['reward_value']} (exp {exp_val}) "
              f"return={r['effective_return_pct']}% (exp {exp_pct}%)")

    print(f"\nScore: {passed}/{len(rows)} ({100*passed/len(rows):.0f}%)")
    return {"passed": passed, "total": len(rows)}


if __name__ == "__main__":
    res = evaluate()
    sys.exit(0 if res["passed"] == res["total"] else 1)
