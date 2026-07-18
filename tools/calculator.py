"""Reward calculator tool (Layer 4).

Pure, deterministic arithmetic — the agent calls this instead of doing math in the LLM.
"""
from __future__ import annotations

from typing import Dict, Optional


def compute_reward(
    spend: float,
    reward_rate: float,
    reward_per_amount: float,
    point_value: float,
    monthly_cap: Optional[float] = None,
    exclusion: bool = False,
) -> Dict:
    """Compute reward value for a single spend on a single card rule.

    units = spend / reward_per_amount * reward_rate, optionally capped at monthly_cap.
    reward_value = units * point_value (rupees).
    """
    if exclusion or not reward_rate:
        return {
            "spend": spend,
            "base_units": 0.0,
            "earned_units": 0.0,
            "reward_value": 0.0,
            "cap_applied": False,
            "effective_return_pct": 0.0,
            "excluded": True,
        }

    base_units = spend / reward_per_amount * reward_rate
    cap_applied = monthly_cap is not None and base_units > monthly_cap
    earned_units = min(base_units, monthly_cap) if monthly_cap is not None else base_units
    reward_value = earned_units * point_value
    effective = (reward_value / spend * 100.0) if spend else 0.0

    return {
        "spend": round(spend, 2),
        "base_units": round(base_units, 2),
        "earned_units": round(earned_units, 2),
        "reward_value": round(reward_value, 2),
        "cap_applied": cap_applied,
        "effective_return_pct": round(effective, 2),
        "excluded": False,
    }


def compute_for_rule(spend: float, rule: Dict) -> Dict:
    """Convenience wrapper that pulls fields from a reward_rules row dict."""
    result = compute_reward(
        spend=spend,
        reward_rate=float(rule.get("reward_rate") or 0),
        reward_per_amount=float(rule.get("reward_per_amount") or 100),
        point_value=float(rule.get("point_value") or 0),
        monthly_cap=(float(rule["monthly_cap"]) if rule.get("monthly_cap") is not None else None),
        exclusion=bool(rule.get("exclusion_flag")),
    )
    result["card_name"] = rule.get("card_name")
    result["reward_unit"] = rule.get("reward_unit")
    result["category"] = rule.get("spend_category")
    result["notes"] = rule.get("notes")
    return result
