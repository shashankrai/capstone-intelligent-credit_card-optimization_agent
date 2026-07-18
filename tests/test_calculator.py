"""Unit tests for the deterministic tools (no API key / DB needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.calculator import compute_reward  # noqa: E402
from tools.transfer_calculator import compute_transfer  # noqa: E402


def test_basic_earn():
    # Rs 50,000 flight on Axis Atlas: 5 miles / Rs 100, value Rs 1 -> Rs 2,500, 5%.
    r = compute_reward(50000, reward_rate=5, reward_per_amount=100, point_value=1.0)
    assert r["earned_units"] == 2500
    assert r["reward_value"] == 2500
    assert r["effective_return_pct"] == 5.0
    assert r["cap_applied"] is False


def test_cap_applied():
    # SBI 5% online on Rs 2,00,000 -> Rs 10,000 capped at Rs 5,000.
    r = compute_reward(200000, reward_rate=5, reward_per_amount=100, point_value=1.0, monthly_cap=5000)
    assert r["earned_units"] == 5000
    assert r["cap_applied"] is True


def test_exclusion():
    r = compute_reward(50000, reward_rate=0, reward_per_amount=100, point_value=1.0, exclusion=True)
    assert r["reward_value"] == 0
    assert r["excluded"] is True


def test_transfer_ratio():
    # 40,000 points at 2:1 -> 20,000 partner units.
    r = compute_transfer(40000, {"transfer_ratio": 2, "minimum_points": 5000,
                                 "partner_name": "X", "partner_type": "hotel", "card_name": "Y"},
                         partner_value=1.0)
    assert r["partner_units_out"] == 20000
    assert r["meets_minimum"] is True
    assert r["estimated_value"] == 20000


if __name__ == "__main__":
    test_basic_earn(); test_cap_applied(); test_exclusion(); test_transfer_ratio()
    print("all calculator tests passed")
