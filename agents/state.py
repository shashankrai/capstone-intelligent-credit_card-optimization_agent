"""Shared LangGraph state for the rewards-optimization agent."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    # --- input ---
    user_id: Optional[str]
    thread_id: Optional[str]
    query: str
    preferences: Dict[str, Any]          # e.g. {"preferred_reward_type": "hotel points"}

    # --- memory (loaded from user_profiles) ---
    profile: Dict[str, Any]

    # --- input guardrail ---
    on_topic: bool
    safety_concern: str

    # --- intent classification / parsing ---
    intent: str                          # single_transaction | monthly_optimization | transfer | comparison | missing_info
    needs_clarification: bool
    clarification_question: str
    spend_items: List[Dict[str, Any]]    # [{"category": "flights", "amount": 50000}]
    candidate_cards: List[str]
    preferred_reward_type: Optional[str]
    points_balance: Optional[float]      # for transfer intent

    # --- retrieval / validation ---
    retrieved_chunks: List[Dict[str, Any]]
    rules: List[Dict[str, Any]]
    transfer_partners: List[Dict[str, Any]]
    effective_dates: Dict[str, Any]      # card_name -> effective_date
    validation: Dict[str, Any]

    # --- computation ---
    calculations: List[Dict[str, Any]]   # per card-category calculator outputs
    card_totals: List[Dict[str, Any]]    # aggregated per card
    allocation: List[Dict[str, Any]]     # per-category best card (monthly optimization)
    transfer_options: List[Dict[str, Any]]

    # --- human-in-the-loop ---
    needs_approval: bool
    approval_prompt: str
    approval_granted: bool

    # --- output ---
    recommended_card: Optional[str]
    estimated_value: Optional[float]
    confidence: str
    final_answer: str
    guardrail: Dict[str, Any]
    query_id: Optional[int]              # recommendation_logs row id (for feedback linkage)

    # --- bookkeeping ---
    input_tokens: int
    output_tokens: int
    latency_ms: int
    halted: bool                         # stopped early (refusal / insufficient / cancelled)
    stage: str                           # last node reached (for the caller / UI)
