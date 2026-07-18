"""Add a card to the knowledge base via two front doors that share ONE pipeline.

Both paths produce identical structured data:
    source (web-searched markdown | uploaded PDF)
        -> data/cards/<stem>.(md|pdf)
        -> ingest_one()        : chunk + embed -> document_chunks
        -> extract_card()      : Claude -> reward_rules + transfer_partners (confidence + citations)

- add_card_from_web(card_name):  Claude web-searches the card's current terms and writes a
  structured markdown doc, then runs the shared pipeline.
- add_card_from_pdf(pdf_bytes, card_name):  saves the PDF, then runs the shared pipeline.

Both require ANTHROPIC_API_KEY (web search / extraction use Claude).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional

import config
import llm
from rag.extract_rules import extract_card
from rag.ingest_pdfs import DocSpec, ingest_one

RETRIEVED_DATE = "2026-07-15"

SPEND_CATEGORIES = "flights, hotels, travel, dining, groceries, online, utilities, rent, fuel, insurance, general"

WEB_DOC_SYSTEM = f"""You research a credit card's CURRENT public reward terms using web search and
compile ONE markdown document. Use only what you find; append "(verify)" to anything uncertain.
Prefer the official issuer site; use reputable aggregators to fill gaps. Cover all of these
spend categories where applicable: {SPEND_CATEGORIES}.

Output ONLY the markdown document, with EXACTLY these headings:
# {{card_name}} — Terms, Reward Rules & Transfer Partners
Issuer: {{issuer}}
Reward currency: (the card's reward unit)
Retrieved date: {RETRIEVED_DATE}
Source: compiled from public web sources listed below — NOT official issuer documentation; verify current terms with the issuer.

## Reward Earning Structure   (category-wise earn rates)
## Exclusions (no rewards earned)
## Reward Caps
## Milestone Benefits
## Redemption Options
## Point Valuation   (assumed rupee value per reward unit)
## Transfer Partners   (one bullet each: "- Name (airline|hotel) — transfer ratio X:Y. Minimum transfer N.")
## Annual Fee & Waiver
## Sources   (the URLs you used)"""


def slugify(card_name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", card_name.strip().lower())
    return s.strip("_") or "card"


def _run_pipeline(spec: DocSpec) -> Dict:
    document_id, n_chunks = ingest_one(spec, reset_card=True)
    counts = extract_card(spec.card_name)
    return {
        "card_name": spec.card_name,
        "document_id": document_id,
        "chunks": n_chunks,
        "reward_rules": counts["reward_rules"],
        "transfer_partners": counts["transfer_partners"],
        "doc_path": str(spec.path),
    }


def add_card_from_web(card_name: str, issuer: Optional[str] = None) -> Dict:
    """Web-search the card via Claude, write data/cards/<stem>.md, then ingest + extract."""
    config.require_api_key()
    stem = slugify(card_name)
    system = WEB_DOC_SYSTEM.format(card_name=card_name, issuer=issuer or "(identify the issuer)")
    doc, _ = llm.web_search_complete(
        system, f"Research and compile the reward terms for the '{card_name}' credit card (India).",
        max_tokens=3500)
    if not doc.strip():
        raise RuntimeError("Web search returned no content for that card.")
    path = config.CARDS_DIR / f"{stem}.md"
    path.write_text(doc.strip() + "\n", encoding="utf-8")

    spec = DocSpec(path, card_name, issuer, "terms_and_rewards", RETRIEVED_DATE,
                   f"web-search:{card_name}")
    return _run_pipeline(spec)


def add_card_from_pdf(pdf_bytes: bytes, card_name: str, issuer: Optional[str] = None,
                      source_url: Optional[str] = None) -> Dict:
    """Save an uploaded PDF to data/cards/<stem>.pdf, then ingest + extract (same pipeline)."""
    config.require_api_key()
    stem = slugify(card_name)
    path = config.CARDS_DIR / f"{stem}.pdf"
    path.write_bytes(pdf_bytes)

    spec = DocSpec(path, card_name, issuer, "terms_and_rewards", None,
                   source_url or f"uploaded-pdf:{path.name}")
    return _run_pipeline(spec)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Add a card via web search or a PDF file.")
    ap.add_argument("card_name")
    ap.add_argument("--pdf", help="path to a PDF file (omit to use web search)")
    ap.add_argument("--issuer", default=None)
    args = ap.parse_args()

    if args.pdf:
        res = add_card_from_pdf(Path(args.pdf).read_bytes(), args.card_name, args.issuer)
    else:
        res = add_card_from_web(args.card_name, args.issuer)
    print(res)
