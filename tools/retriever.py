"""Structured retrieval tool — reward_rules / transfer_partners / card list.

Complements the unstructured RAG retrieval (rag/retrieval.py) with exact lookups
from the structured tables, which the calculator can use directly.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from database.db import get_conn


def list_cards() -> List[str]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT card_name FROM reward_rules ORDER BY card_name;")
        return [r["card_name"] for r in cur.fetchall()]


def fetch_rule(card_name: str, category: str) -> Optional[Dict]:
    """Best matching reward rule for a card+category, falling back to 'general'."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM reward_rules WHERE card_name=%s AND spend_category=%s LIMIT 1;",
            (card_name, category),
        )
        row = cur.fetchone()
        if row:
            return dict(row)
        cur.execute(
            "SELECT * FROM reward_rules WHERE card_name=%s AND spend_category='general' LIMIT 1;",
            (card_name,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def fetch_rules_for_category(category: str, cards: Optional[List[str]] = None) -> List[Dict]:
    """One best rule per card for the given category."""
    target_cards = cards or list_cards()
    out: List[Dict] = []
    for card in target_cards:
        rule = fetch_rule(card, category)
        if rule:
            out.append(rule)
    return out


def effective_dates_for(cards: Optional[List[str]] = None) -> Dict[str, str]:
    """Map card_name -> effective_date (from card_documents) for cards we have docs for."""
    clause, params = "", []
    if cards:
        clause = "WHERE card_name = ANY(%s)"
        params.append(cards)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT card_name, MAX(effective_date) AS effective_date "
            f"FROM card_documents {clause} GROUP BY card_name;", params
        )
        return {r["card_name"]: (str(r["effective_date"]) if r["effective_date"] else None)
                for r in cur.fetchall()}


def fetch_transfer_partners(cards: Optional[List[str]] = None,
                            partner_type: Optional[str] = None) -> List[Dict]:
    clauses = []
    params: list = []
    if cards:
        clauses.append("card_name = ANY(%s)")
        params.append(cards)
    if partner_type:
        clauses.append("partner_type = %s")
        params.append(partner_type)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT * FROM transfer_partners {where} ORDER BY card_name, transfer_ratio;", params)
        return [dict(r) for r in cur.fetchall()]
