"""Structured-rule extraction pipeline.

Reads the ingested document_chunks for each card and uses Claude to extract clean,
calculable reward_rules + transfer_partners — with a confidence score and a citation
back to the source chunk. This is how the structured tables get populated from REAL
card PDFs (vs. the hand-authored fallback in database/seed_data.py).

Run:  python -m rag.extract_rules      (requires ANTHROPIC_API_KEY + ingested docs)
"""
from __future__ import annotations

import json
from typing import Dict, List

import config
import llm
from database.db import get_conn

SPEND_CATEGORIES = [
    "flights", "hotels", "travel", "dining", "groceries", "online",
    "utilities", "rent", "fuel", "insurance", "general",
]

EXTRACT_SYSTEM = f"""You extract structured credit-card reward rules from the card's own document chunks.

Return rules ONLY for what the chunks actually state — never invent rates, caps, partners,
or exclusions. If the document doesn't cover a category, omit it (do not guess).

For reward_rules, express earning as `reward_rate` units per `reward_per_amount` rupees
(e.g. 5 points per 150 -> reward_rate=5, reward_per_amount=150). Use these spend_category
values only: {", ".join(SPEND_CATEGORIES)}. Mark exclusion_flag=true for categories the
document says earn nothing. `point_value` is the assumed rupee value of one reward unit
(use the document's stated redemption value; for direct cashback use 1.0). `monthly_cap`/
`annual_cap` are caps on reward UNITS (null if none). Set source_chunk_index to the index
of the chunk (as labelled "[chunk N]") that supports each rule, and confidence_score in
[0,1] reflecting how explicit the evidence was.

For transfer_partners, transfer_ratio is card-units-per-1-partner-unit (2:1 -> 2)."""

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "reward_rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "spend_category": {"type": "string", "enum": SPEND_CATEGORIES},
                    "reward_type": {"type": "string", "enum": ["points", "miles", "cashback"]},
                    "reward_rate": {"type": "number"},
                    "reward_per_amount": {"type": "number"},
                    "reward_unit": {"type": "string"},
                    "monthly_cap": {"type": ["number", "null"]},
                    "annual_cap": {"type": ["number", "null"]},
                    "point_value": {"type": "number"},
                    "exclusion_flag": {"type": "boolean"},
                    "milestone_flag": {"type": "boolean"},
                    "notes": {"type": "string"},
                    "source_chunk_index": {"type": "integer"},
                    "confidence_score": {"type": "number"},
                },
                "required": ["spend_category", "reward_type", "reward_rate", "reward_per_amount",
                             "reward_unit", "point_value", "exclusion_flag", "source_chunk_index",
                             "confidence_score"],
                "additionalProperties": False,
            },
        },
        "transfer_partners": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "partner_name": {"type": "string"},
                    "partner_type": {"type": "string", "enum": ["airline", "hotel"]},
                    "transfer_ratio": {"type": "number"},
                    "minimum_points": {"type": ["number", "null"]},
                    "maximum_points": {"type": ["number", "null"]},
                    "source_chunk_index": {"type": "integer"},
                },
                "required": ["partner_name", "partner_type", "transfer_ratio", "source_chunk_index"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["reward_rules", "transfer_partners"],
    "additionalProperties": False,
}


def _chunks_by_card() -> Dict[str, List[Dict]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT chunk_id, document_id, card_name, page_number, chunk_text "
            "FROM document_chunks ORDER BY card_name, chunk_id;"
        )
        rows = [dict(r) for r in cur.fetchall()]
    by_card: Dict[str, List[Dict]] = {}
    for r in rows:
        by_card.setdefault(r["card_name"], []).append(r)
    return by_card


def _store(cur, card: str, doc_id, chunks: List[Dict], data: Dict) -> Dict[str, int]:
    """Insert extracted rules/partners for one card. Returns counts."""
    def chunk_id_for(idx):
        return chunks[idx]["chunk_id"] if isinstance(idx, int) and 0 <= idx < len(chunks) else None

    n_rules = n_partners = 0
    for r in data.get("reward_rules", []):
        cur.execute(
            """INSERT INTO reward_rules
               (card_name, spend_category, reward_type, reward_rate, reward_per_amount,
                reward_unit, monthly_cap, annual_cap, point_value, exclusion_flag,
                milestone_flag, notes, source_document_id, source_chunk_id, confidence_score)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);""",
            (card, r["spend_category"], r["reward_type"], r["reward_rate"],
             r["reward_per_amount"], r["reward_unit"], r.get("monthly_cap"),
             r.get("annual_cap"), r["point_value"], r["exclusion_flag"],
             r.get("milestone_flag", False), r.get("notes", ""), doc_id,
             chunk_id_for(r.get("source_chunk_index")), r["confidence_score"]),
        )
        n_rules += 1
    for p in data.get("transfer_partners", []):
        cur.execute(
            """INSERT INTO transfer_partners
               (card_name, partner_name, partner_type, transfer_ratio, minimum_points,
                maximum_points, effective_date, source_document_id, source_chunk_id)
               VALUES (%s,%s,%s,%s,%s,%s,NULL,%s,%s);""",
            (card, p["partner_name"], p["partner_type"], p["transfer_ratio"],
             p.get("minimum_points"), p.get("maximum_points"), doc_id,
             chunk_id_for(p.get("source_chunk_index"))),
        )
        n_partners += 1
    return {"reward_rules": n_rules, "transfer_partners": n_partners}


def _extract_chunks(card: str, chunks: List[Dict]) -> Dict:
    labelled = "\n\n".join(f"[chunk {i}] (page {c['page_number']})\n{c['chunk_text']}"
                           for i, c in enumerate(chunks))
    data, _ = llm.complete_json(EXTRACT_SYSTEM, f"CARD: {card}\n\nDOCUMENT CHUNKS:\n{labelled}",
                                EXTRACT_SCHEMA, max_tokens=4096)
    return data


def extract_card(card_name: str) -> Dict[str, int]:
    """(Re)extract structured rules for ONE card from its chunks. Shared by the add-card flows."""
    config.require_api_key()
    chunks = _chunks_by_card().get(card_name)
    if not chunks:
        raise RuntimeError(f"No document_chunks found for '{card_name}'. Ingest it first.")
    data = _extract_chunks(card_name, chunks)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM reward_rules WHERE card_name=%s;", (card_name,))
        cur.execute("DELETE FROM transfer_partners WHERE card_name=%s;", (card_name,))
        counts = _store(cur, card_name, chunks[0]["document_id"], chunks, data)
    print(f"  {card_name}: extracted {counts['reward_rules']} rules, {counts['transfer_partners']} partners")
    return counts


def extract_and_store() -> Dict[str, int]:
    """Extract structured rules for every card from its chunks and store them."""
    config.require_api_key()
    by_card = _chunks_by_card()
    if not by_card:
        raise RuntimeError("No document_chunks found. Run ingestion first (python -m rag.ingest_pdfs).")

    totals = {"reward_rules": 0, "transfer_partners": 0}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE reward_rules, transfer_partners RESTART IDENTITY;")
        for card, chunks in by_card.items():
            data = _extract_chunks(card, chunks)
            counts = _store(cur, card, chunks[0]["document_id"], chunks, data)
            totals = {k: totals[k] + counts[k] for k in totals}
            print(f"  {card}: extracted {counts['reward_rules']} rules, {counts['transfer_partners']} partners")
    return totals


if __name__ == "__main__":
    result = extract_and_store()
    print(f"Extracted {result['reward_rules']} reward rules, {result['transfer_partners']} partners.")
