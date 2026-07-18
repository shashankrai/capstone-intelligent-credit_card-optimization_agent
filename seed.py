"""One-shot setup: create schema, ingest documents (RAG), seed structured tables.

Usage:  python seed.py
"""
from __future__ import annotations

from database.db import get_conn, init_schema
from database.seed_data import REWARD_RULES, TRANSFER_PARTNERS
from rag.ingest_pdfs import ingest_all


def _doc_id_for_card(cur, card_name: str):
    cur.execute("SELECT document_id FROM card_documents WHERE card_name=%s LIMIT 1;", (card_name,))
    row = cur.fetchone()
    return row["document_id"] if row else None


def seed_structured() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE reward_rules, transfer_partners RESTART IDENTITY;")

        for r in REWARD_RULES:
            doc_id = _doc_id_for_card(cur, r["card_name"])
            cur.execute(
                """INSERT INTO reward_rules
                   (card_name, spend_category, reward_type, reward_rate, reward_per_amount,
                    reward_unit, monthly_cap, annual_cap, point_value, exclusion_flag,
                    milestone_flag, notes, source_document_id, confidence_score)
                   VALUES (%(card_name)s, %(spend_category)s, %(reward_type)s, %(reward_rate)s,
                           %(reward_per_amount)s, %(reward_unit)s, %(monthly_cap)s, %(annual_cap)s,
                           %(point_value)s, %(exclusion_flag)s, %(milestone_flag)s, %(notes)s,
                           %(doc_id)s, %(confidence_score)s);""",
                {**r, "doc_id": doc_id},
            )

        for p in TRANSFER_PARTNERS:
            doc_id = _doc_id_for_card(cur, p["card_name"])
            cur.execute(
                """INSERT INTO transfer_partners
                   (card_name, partner_name, partner_type, transfer_ratio, minimum_points,
                    maximum_points, effective_date, source_document_id)
                   VALUES (%(card_name)s, %(partner_name)s, %(partner_type)s, %(transfer_ratio)s,
                           %(minimum_points)s, %(maximum_points)s, '2026-01-01', %(doc_id)s);""",
                {**p, "doc_id": doc_id},
            )


def main(extract: bool = False) -> None:
    print("1/3  Creating schema...")
    init_schema()

    print("2/3  Ingesting card documents (RAG: extract -> chunk -> embed -> pgvector)...")
    docs, chunks = ingest_all()
    print(f"     -> {docs} documents, {chunks} chunks.")

    if extract:
        print("3/3  Extracting structured rules from documents with Claude...")
        from rag.extract_rules import extract_and_store

        extract_and_store()
    else:
        print("3/3  Seeding hand-authored structured rules (offline, matches the illustrative .md docs)...")
        seed_structured()

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM reward_rules;")
        nr = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM transfer_partners;")
        nt = cur.fetchone()["n"]
    print(f"     -> {nr} reward rules, {nt} transfer partners.")
    print("\nSetup complete. Try:  python cli.py \"I am spending Rs 50,000 on flights. Which card should I use?\"")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Set up the rewards-agent database.")
    ap.add_argument("--extract", action="store_true",
                    help="Extract structured rules from the ingested PDFs using Claude "
                         "(needs ANTHROPIC_API_KEY). Default seeds hand-authored rules offline.")
    args = ap.parse_args()
    main(extract=args.extract)
