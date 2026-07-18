"""Point transfer calculator tool (Layer 4 / Use Case 3).

Given a points balance and transfer-partner rows, compute partner units obtained and
an estimated value, honouring transfer ratios and minimum-transfer thresholds.
"""
from __future__ import annotations

from typing import Dict, List, Optional


def compute_transfer(points: float, partner: Dict, partner_value: Optional[float] = None) -> Dict:
    """transfer_ratio is card-units-per-1-partner-unit (e.g. 2 means 2 card pts -> 1 partner pt)."""
    ratio = float(partner.get("transfer_ratio") or 1)
    minimum = float(partner.get("minimum_points") or 0)
    meets_min = points >= minimum
    partner_units = points / ratio if ratio else 0.0
    # If caller supplies an estimated partner-unit value (in rupees), value the transfer.
    est_value = round(partner_units * partner_value, 2) if partner_value is not None else None
    return {
        "card_name": partner.get("card_name"),
        "partner_name": partner.get("partner_name"),
        "partner_type": partner.get("partner_type"),
        "transfer_ratio": ratio,
        "points_in": points,
        "partner_units_out": round(partner_units, 2),
        "minimum_points": minimum,
        "meets_minimum": meets_min,
        "estimated_value": est_value,
    }


def compare_transfers(points: float, partners: List[Dict],
                      partner_value: Optional[float] = None) -> List[Dict]:
    results = [compute_transfer(points, p, partner_value) for p in partners]
    results.sort(key=lambda r: r["partner_units_out"], reverse=True)
    return results
