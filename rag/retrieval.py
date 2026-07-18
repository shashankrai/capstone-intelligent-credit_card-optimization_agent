"""Layer 2 — Retrieval.

Hybrid retrieval over document_chunks: vector similarity (pgvector cosine) blended with
a keyword (substring) signal. Optionally filter to a set of candidate cards.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import config
from database.db import get_conn
from rag.embeddings import embed_query


def retrieve(
    query: str,
    top_k: int = config.RETRIEVE_TOP_K,
    cards: Optional[List[str]] = None,
    keywords: Optional[List[str]] = None,
) -> List[Dict]:
    """Return the most relevant chunks: card_name, chunk_text, page_number, similarity, score."""
    qvec = embed_query(query)
    fetch = max(top_k * 2, top_k)

    # Build SQL + params in placeholder order.
    where = ""
    params: list = [qvec]                 # 1) similarity expression in SELECT
    if cards:
        where = "WHERE card_name = ANY(%s)"
        params.append(cards)              # 2) optional card filter
    params.append(qvec)                   # 3) ORDER BY distance
    params.append(fetch)                  # 4) LIMIT

    sql = f"""
        SELECT chunk_id, card_name, chunk_text, page_number,
               1 - (embedding <=> %s::vector) AS similarity
        FROM document_chunks
        {where}
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]

    # Lightweight keyword boost (hybrid): bump chunks containing query keywords.
    kw = keywords or [w for w in query.lower().split() if len(w) > 3]
    for r in rows:
        text_l = r["chunk_text"].lower()
        hits = sum(1 for k in kw if k in text_l)
        r["similarity"] = float(r["similarity"])
        r["score"] = r["similarity"] + 0.03 * hits

    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:top_k]


def format_context(chunks: List[Dict]) -> str:
    """Render retrieved chunks into a grounding context block with citations."""
    lines = []
    for i, c in enumerate(chunks, 1):
        lines.append(
            f"[Source {i} | {c['card_name']} | page {c['page_number']} | "
            f"relevance {c['score']:.2f}]\n{c['chunk_text']}"
        )
    return "\n\n".join(lines)
