"""Reproducible web collector — refresh card docs from public web pages.

For each card it fetches a curated list of public URLs, strips the HTML to text, and asks
Claude to compile a clean structured markdown document (same template the RAG pipeline ingests),
with a provenance header (source URLs + retrieved date). Output goes to data/cards/<stem>.md.

This is the automated counterpart to the manual/agent-assisted collection. Notes:
- Requires ANTHROPIC_API_KEY and outbound web access. On a restricted corporate network some
  bank/aggregator URLs may be blocked (HTTP 403) — those are skipped and logged; add more
  reachable sources or run off-network.
- It does NOT do open-ended search (that needs a search API); it fetches the curated URLs below.
- Always human-review the generated markdown before trusting it. Data is illustrative until verified.

Usage:
  python -m rag.collect_web                 # refresh all cards
  python -m rag.collect_web axis_atlas      # refresh one card
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List

import requests

import config  # noqa: F401  (imported for truststore TLS injection)
import llm

RETRIEVED_DATE = "2026-07-15"  # stamp; pass a real date in when you re-run

# Curated public sources per card. Add/replace URLs as they change.
SOURCES: Dict[str, Dict] = {
    "axis_atlas": {
        "card_name": "Axis Atlas", "issuer": "Axis Bank", "currency": "EDGE Miles",
        "urls": ["https://www.axisbank.com/",
                 "https://cardmaven.in/axis-bank-atlas-credit-card/",
                 "https://www.paisabazaar.com/axis-bank/atlas-credit-card/"],
    },
    "hdfc_diners_club_black": {
        "card_name": "HDFC Diners Club Black", "issuer": "HDFC Bank", "currency": "Reward Points",
        "urls": ["https://www.hdfcbank.com/",
                 "https://www.paisabazaar.com/hdfc-bank/hdfc-diners-club-black-credit-card/"],
    },
    "hdfc_infinia": {
        "card_name": "HDFC Infinia", "issuer": "HDFC Bank", "currency": "Reward Points",
        "urls": ["https://www.hdfcbank.com/",
                 "https://milesahead.club/blog/hdfc-infinia-reward-points-guide"],
    },
    "amex_platinum_travel": {
        "card_name": "American Express Platinum Travel", "issuer": "American Express",
        "currency": "Membership Rewards Points",
        "urls": ["https://www.americanexpress.com/in/",
                 "https://www.cardexpert.in/amex-platinum-travel-credit-card-review/"],
    },
    "sbi_cashback": {
        "card_name": "SBI Cashback", "issuer": "SBI Card", "currency": "Direct Cashback",
        "urls": ["https://www.sbicard.com/en/personal/credit-cards/rewards/cashback-sbi-card.page",
                 "https://cardinsider.com/sbi-card/cashback-sbi-credit-card/"],
    },
}

TEMPLATE = """Compile a single markdown document about the credit card below, using ONLY the
provided page text. Do not invent numbers; append "(verify)" to anything uncertain or unstated.

Use EXACTLY these headings:
# {card_name} — Terms, Reward Rules & Transfer Partners
Issuer: {issuer}
Reward currency: {currency}
Retrieved date: {date}
Source: compiled from public sources listed below — NOT official issuer documentation; verify current terms with the issuer.

## Reward Earning Structure   (category-wise rates)
## Exclusions (no rewards earned)
## Reward Caps
## Milestone Benefits
## Redemption Options
## Point Valuation
## Transfer Partners   (one bullet each: "- Name (airline|hotel) — transfer ratio X:Y. Minimum transfer N.")
## Annual Fee & Waiver
## Sources   (the URLs provided)

Output ONLY the markdown document."""

_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_ANGLE = re.compile(r"<[^>]+>")
_WS = re.compile(r"\n\s*\n\s*")


def _fetch_text(url: str) -> str:
    try:
        resp = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0 (capstone-collector)"})
        resp.raise_for_status()
    except Exception as exc:
        print(f"    [skip] {url} -> {type(exc).__name__}: {str(exc)[:80]}")
        return ""
    html = _TAG.sub(" ", resp.text)
    text = _WS.sub("\n\n", _ANGLE.sub(" ", html))
    return f"\n\n===== SOURCE: {url} =====\n{text[:12000]}"


def collect(stem: str) -> bool:
    spec = SOURCES[stem]
    print(f"  collecting {spec['card_name']} ...")
    corpus = "".join(_fetch_text(u) for u in spec["urls"])
    if not corpus.strip():
        print(f"    no reachable sources for {stem}; keeping existing doc.")
        return False
    system = TEMPLATE.format(card_name=spec["card_name"], issuer=spec["issuer"],
                             currency=spec["currency"], date=RETRIEVED_DATE)
    doc, _ = llm.complete(system, f"PAGE TEXT:\n{corpus}", max_tokens=3000)
    out = config.CARDS_DIR / f"{stem}.md"
    out.write_text(doc.strip() + "\n", encoding="utf-8")
    print(f"    wrote {out}")
    return True


def main(stems: List[str]) -> None:
    config.require_api_key()
    targets = stems or list(SOURCES)
    for stem in targets:
        if stem not in SOURCES:
            print(f"  unknown card '{stem}'; known: {list(SOURCES)}")
            continue
        collect(stem)
    print("\nDone. Review the generated data/cards/*.md, then re-run: python seed.py --extract")


if __name__ == "__main__":
    main(sys.argv[1:])
