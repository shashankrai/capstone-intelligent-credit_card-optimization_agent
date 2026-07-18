"""Structured reward rules + transfer partners, extracted from the card documents.

These mirror data/cards/*.md (the source of truth) but in a clean, calculable form
(reward_rules + transfer_partners tables). Earn rate is expressed as
`reward_rate` units per `reward_per_amount` rupees, valued at `point_value` rupees/unit.
`monthly_cap` is a cap on reward UNITS earned per month (None = uncapped).
"""
from __future__ import annotations

from typing import Dict, List

# Categories every card should answer for (used to expand "general" defaults).
SPEND_CATEGORIES = [
    "flights", "hotels", "travel", "dining", "groceries", "online",
    "utilities", "rent", "fuel", "insurance", "general",
]


def _rule(card, category, rtype, rate, per, unit, value,
          monthly_cap=None, exclusion=False, milestone=False, notes="", conf=0.9):
    return dict(
        card_name=card, spend_category=category, reward_type=rtype,
        reward_rate=rate, reward_per_amount=per, reward_unit=unit, point_value=value,
        monthly_cap=monthly_cap, annual_cap=None, exclusion_flag=exclusion,
        milestone_flag=milestone, notes=notes, confidence_score=conf,
    )


def _build_rules() -> List[Dict]:
    rules: List[Dict] = []

    # ---- Axis Atlas: travel accelerated 5 EDGE Miles/₹100 (cap ~10,000 miles/mo), else 2/₹100
    A = "Axis Atlas"
    travel_note = "Accelerated travel rate; capped at the value of ₹2,00,000 travel spend/month (~10,000 miles)."
    for cat in ("flights", "hotels", "travel"):
        rules.append(_rule(A, cat, "miles", 5, 100, "EDGE Miles", 1.0, monthly_cap=10000, notes=travel_note))
    for cat in ("dining", "groceries", "online", "general"):
        rules.append(_rule(A, cat, "miles", 2, 100, "EDGE Miles", 1.0, notes="General earn rate."))
    for cat in ("rent", "fuel", "insurance", "utilities"):
        rules.append(_rule(A, cat, "miles", 0, 100, "EDGE Miles", 1.0, exclusion=True,
                           notes="Excluded category — earns no EDGE Miles."))

    # ---- HDFC Diners Club Black: base 5 RP/₹150 (direct). SmartBuy 10X capped 7,500 RP/mo.
    D = "HDFC Diners Club Black"
    sb = "Base rate on direct spend. SmartBuy portal earns 10X (~33.3 RP/₹150), capped 7,500 RP/month."
    for cat in ("flights", "hotels", "travel", "dining", "groceries", "online", "general"):
        rules.append(_rule(D, cat, "points", 5, 150, "Reward Points", 1.0, notes=sb))
    for cat in ("rent", "fuel", "insurance", "utilities"):
        rules.append(_rule(D, cat, "points", 0, 150, "Reward Points", 1.0, exclusion=(cat in ("rent", "fuel")),
                           notes="Rent and fuel are excluded." if cat in ("rent", "fuel") else "Earns base rate only."))

    # ---- HDFC Infinia: base 5 RP/₹150 (direct). SmartBuy 10X capped 15,000 RP/mo.
    I = "HDFC Infinia"
    sbi = "Base rate on direct spend. SmartBuy portal earns 10X (~33.3 RP/₹150), capped 15,000 RP/month."
    for cat in ("flights", "hotels", "travel", "dining", "groceries", "online", "general"):
        rules.append(_rule(I, cat, "points", 5, 150, "Reward Points", 1.0, notes=sbi))
    for cat in ("rent", "fuel"):
        rules.append(_rule(I, cat, "points", 0, 150, "Reward Points", 1.0, exclusion=True,
                           notes="Excluded category."))
    for cat in ("insurance", "utilities"):
        rules.append(_rule(I, cat, "points", 5, 150, "Reward Points", 1.0, notes="Earns base rate."))

    # ---- Amex Platinum Travel: 1 MR/₹50 base, value ~₹0.5. Milestone-driven.
    X = "American Express Platinum Travel"
    ms = ("Milestone card (from Mar 2026): ₹1.9L/yr -> 7,500 bonus MR; ₹4L/yr -> +10,000 MR; "
          "₹7L/yr -> +22,500 MR + ₹10,000 Taj voucher.")
    for cat in ("flights", "hotels", "travel", "dining", "groceries", "online", "general"):
        rules.append(_rule(X, cat, "points", 1, 50, "MR Points", 0.5, milestone=True, notes=ms))
    for cat in ("fuel", "insurance", "utilities"):
        rules.append(_rule(X, cat, "points", 0, 50, "MR Points", 0.5, exclusion=True, notes="Excluded category."))
    rules.append(_rule(X, "rent", "points", 1, 50, "MR Points", 0.5, notes="Earns base rate (verify merchant)."))

    # ---- SBI Cashback: 5% online (cap ₹5,000/mo), 1% offline. Cashback = rupees.
    S = "SBI Cashback"
    cap_note = "Total cashback capped at ₹4,000/statement month (online + offline ₹2,000 each; from Apr 2026)."
    for cat in ("flights", "hotels", "online"):
        rules.append(_rule(S, cat, "cashback", 5, 100, "% cashback", 1.0, monthly_cap=4000,
                           notes="Online spend earns 5%. " + cap_note))
    for cat in ("dining", "groceries", "travel", "general"):
        rules.append(_rule(S, cat, "cashback", 1, 100, "% cashback", 1.0, monthly_cap=4000,
                           notes="Offline/other spend earns 1%. " + cap_note))
    for cat in ("rent", "fuel", "insurance", "utilities"):
        rules.append(_rule(S, cat, "cashback", 0, 100, "% cashback", 1.0, exclusion=True,
                           notes="Excluded category — earns no cashback."))

    return rules


def _build_partners() -> List[Dict]:
    def p(card, name, ptype, ratio, minp):
        return dict(card_name=card, partner_name=name, partner_type=ptype,
                    transfer_ratio=ratio, minimum_points=minp, maximum_points=None)

    # transfer_ratio = card units per 1 partner unit. Real 2026 data (see data/cards/*.md);
    # Atlas 1:2 favourable partners modelled as ratio 0.5 (1 mile -> 2 partner units).
    return [
        # Axis Atlas — most partners 1:2 (ratio 0.5); Apr-2026 additions BA/Finnair are 2:1.
        p("Axis Atlas", "Singapore Airlines KrisFlyer", "airline", 0.5, 500),
        p("Axis Atlas", "Air France-KLM Flying Blue", "airline", 0.5, 500),
        p("Axis Atlas", "Air India Maharaja Club", "airline", 0.5, 500),
        p("Axis Atlas", "ITC Hotels (Club ITC)", "hotel", 0.5, 500),
        p("Axis Atlas", "IHG One Rewards", "hotel", 0.5, 500),
        p("Axis Atlas", "British Airways Executive Club", "airline", 2, 500),
        # HDFC Diners Club Black — mix of 1:1 and 2:1.
        p("HDFC Diners Club Black", "Air France-KLM Flying Blue", "airline", 1, 100),
        p("HDFC Diners Club Black", "Singapore Airlines KrisFlyer", "airline", 1, 100),
        p("HDFC Diners Club Black", "British Airways Executive Club", "airline", 2, 100),
        p("HDFC Diners Club Black", "IHG One Rewards", "hotel", 1, 100),
        p("HDFC Diners Club Black", "Marriott Bonvoy", "hotel", 2, 100),
        # HDFC Infinia — mix of 1:1 and 2:1.
        p("HDFC Infinia", "Singapore Airlines KrisFlyer", "airline", 1, 100),
        p("HDFC Infinia", "Air France-KLM Flying Blue", "airline", 1, 100),
        p("HDFC Infinia", "Air Canada Aeroplan", "airline", 2, 100),
        p("HDFC Infinia", "IHG One Rewards", "hotel", 1, 100),
        p("HDFC Infinia", "Marriott Bonvoy", "hotel", 2, 100),
        # Amex Platinum Travel — airlines 2:1, Marriott 1:1.
        p("American Express Platinum Travel", "Singapore Airlines KrisFlyer", "airline", 2, 800),
        p("American Express Platinum Travel", "Emirates Skywards", "airline", 2, 800),
        p("American Express Platinum Travel", "Marriott Bonvoy", "hotel", 1, 1000),
    ]


REWARD_RULES = _build_rules()
TRANSFER_PARTNERS = _build_partners()
