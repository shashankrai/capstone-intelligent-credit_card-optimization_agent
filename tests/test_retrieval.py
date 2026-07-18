"""Retrieval tests (deterministic; needs a seeded DB, no API key)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.retrieval import retrieve  # noqa: E402
from tools.retriever import fetch_rule, list_cards  # noqa: E402


def test_cards_seeded():
    cards = list_cards()
    assert len(cards) >= 4, f"expected >=4 cards, got {cards}"


def test_retrieve_returns_chunks():
    chunks = retrieve("flight travel reward accelerated", top_k=5)
    assert chunks, "retrieval returned no chunks"
    assert all("card_name" in c and "score" in c for c in chunks)


def test_card_filter():
    chunks = retrieve("reward rules", top_k=5, cards=["Axis Atlas"])
    assert chunks and all(c["card_name"] == "Axis Atlas" for c in chunks)


def test_exclusions_present():
    # Every card should have an explicit rule for rent (excluded on most).
    for card in list_cards():
        rule = fetch_rule(card, "rent")
        assert rule is not None, f"{card} missing a rent rule/fallback"


if __name__ == "__main__":
    test_cards_seeded()
    test_retrieve_returns_chunks()
    test_card_filter()
    test_exclusions_present()
    print("all retrieval tests passed")
