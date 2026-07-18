"""Rule validation tool (graph node 5 helper).

Decides whether retrieved evidence is strong enough to answer. If not, the agent
should say it does not have enough information rather than guessing.
"""
from __future__ import annotations

from typing import Dict, List

MIN_SIMILARITY = 0.30      # best chunk must clear this
MIN_STRONG_CHUNKS = 1      # at least this many chunks above MIN_SIMILARITY


def validate_evidence(chunks: List[Dict], rules: List[Dict]) -> Dict:
    """Return {valid: bool, reason: str, confidence: 'high'|'medium'|'low'}."""
    if not chunks and not rules:
        return {"valid": False, "reason": "No documents or structured rules were retrieved.",
                "confidence": "low"}

    strong = [c for c in chunks if c.get("score", 0) >= MIN_SIMILARITY]
    best = max((c.get("score", 0) for c in chunks), default=0.0)

    if len(strong) < MIN_STRONG_CHUNKS and not rules:
        return {
            "valid": False,
            "reason": f"Retrieved evidence is weak (best relevance {best:.2f}); "
                      "not enough grounding to make a confident recommendation.",
            "confidence": "low",
        }

    # Confidence heuristic: structured rules present + strong chunks -> higher.
    if rules and len(strong) >= 2 and best >= 0.5:
        confidence = "high"
    elif rules or len(strong) >= 1:
        confidence = "medium"
    else:
        confidence = "low"

    return {"valid": True, "reason": "Sufficient grounded evidence retrieved.",
            "confidence": confidence}
