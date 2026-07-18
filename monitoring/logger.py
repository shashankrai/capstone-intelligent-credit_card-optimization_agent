"""Monitoring — persist every recommendation to recommendation_logs (Layer / Stage 3)."""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from database.db import get_conn


def log_recommendation(
    *,
    user_id: Optional[str],
    query_text: str,
    intent: str,
    retrieved_chunks: List[Dict],
    recommended_card: Optional[str],
    estimated_value: Optional[float],
    confidence: str,
    guardrail_passed: bool,
    latency_ms: int,
    input_tokens: int,
    output_tokens: int,
    final_answer: str,
) -> int:
    chunk_meta = [
        {"card_name": c.get("card_name"), "page": c.get("page_number"),
         "score": round(float(c.get("score", 0)), 3)}
        for c in retrieved_chunks
    ]
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO recommendation_logs
               (user_id, query_text, intent, retrieved_chunks, recommended_card,
                estimated_value, confidence, guardrail_passed, latency_ms,
                input_tokens, output_tokens, final_answer)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING query_id;""",
            (user_id, query_text, intent, json.dumps(chunk_meta), recommended_card,
             estimated_value, confidence, guardrail_passed, latency_ms,
             input_tokens, output_tokens, final_answer),
        )
        return cur.fetchone()["query_id"]


def recent_logs(limit: int = 20) -> List[Dict]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT query_id, query_text, intent, recommended_card, estimated_value, "
            "confidence, guardrail_passed, latency_ms, input_tokens, output_tokens, created_at "
            "FROM recommendation_logs ORDER BY query_id DESC LIMIT %s;",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
