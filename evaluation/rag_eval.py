"""Retrieval evaluation — Precision@K, Recall@K, MRR (§15 A).

Deterministic: needs a seeded DB but NO API key (retrieval is local).
Relevance = a retrieved chunk whose card_name matches the labelled expected card.

Usage:  python evaluation/rag_eval.py [K]
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from rag.retrieval import retrieve  # noqa: E402

LABELS = Path(__file__).resolve().parent / "retrieval_labels.csv"


def evaluate(k: int = config.RETRIEVE_TOP_K) -> dict:
    rows = list(csv.DictReader(LABELS.open()))
    p_sum = r_sum = mrr_sum = 0.0

    print(f"Retrieval eval @K={k} over {len(rows)} labelled queries\n")
    for row in rows:
        expected = row["expected_card"]
        chunks = retrieve(row["query"], top_k=k)
        hits = [c for c in chunks if c["card_name"] == expected]
        n_relevant_total = 1  # one expected card per label

        precision = len(hits) / k
        recall = min(len(hits), n_relevant_total) / n_relevant_total
        rank = next((i + 1 for i, c in enumerate(chunks) if c["card_name"] == expected), None)
        rr = (1.0 / rank) if rank else 0.0

        p_sum += precision
        r_sum += recall
        mrr_sum += rr
        mark = "✓" if rank == 1 else ("·" if rank else "✗")
        print(f"  {mark} expected={expected:38s} rank={rank}  P@K={precision:.2f} RR={rr:.2f}")

    n = len(rows)
    result = {"precision_at_k": p_sum / n, "recall_at_k": r_sum / n, "mrr": mrr_sum / n, "k": k}
    print(f"\nPrecision@{k}={result['precision_at_k']:.3f}  "
          f"Recall@{k}={result['recall_at_k']:.3f}  MRR={result['mrr']:.3f}")
    return result


if __name__ == "__main__":
    kk = int(sys.argv[1]) if len(sys.argv) > 1 else config.RETRIEVE_TOP_K
    evaluate(kk)
