"""LangGraph node functions. Each takes AgentState and returns a partial-state update."""
from __future__ import annotations

import json
from typing import Dict, List

from langgraph.types import interrupt

import llm
from agents import prompts
from agents.state import AgentState
from database.models import get_profile, upsert_profile
from rag.retrieval import format_context, retrieve
from tools.calculator import compute_for_rule
from tools.retriever import (effective_dates_for, fetch_rule, fetch_transfer_partners,
                             list_cards)
from tools.rule_validator import validate_evidence
from tools.transfer_calculator import compare_transfers

DEFAULT_POINT_VALUE = 1.0  # assumed rupee value of a transferred partner unit


def _add_tokens(state: AgentState, usage: Dict[str, int]) -> None:
    state["input_tokens"] = state.get("input_tokens", 0) + usage.get("input_tokens", 0)
    state["output_tokens"] = state.get("output_tokens", 0) + usage.get("output_tokens", 0)


# --------------------------------------------------------------------------- #
# Node 0: load user memory
# --------------------------------------------------------------------------- #
def memory_load_node(state: AgentState) -> AgentState:
    state["stage"] = "memory_load"
    profile = None
    try:
        if state.get("user_id"):
            profile = get_profile(state["user_id"])
    except Exception as exc:  # memory is best-effort, never block the query
        print(f"[memory] load failed: {exc}")
    state["profile"] = profile or {}
    # Seed preferences from the stored profile (explicit request can override later).
    prefs = dict(state.get("preferences") or {})
    if profile:
        prefs.setdefault("preferred_reward_type", profile.get("preferred_reward_type"))
        prefs.setdefault("point_valuation", profile.get("point_valuation"))
    state["preferences"] = prefs
    return state


# --------------------------------------------------------------------------- #
# Node 1+2+3: classify intent, input guardrail, parse the query
# --------------------------------------------------------------------------- #
def classify_node(state: AgentState) -> AgentState:
    state["stage"] = "classify"
    parsed, usage = llm.complete_json(prompts.CLASSIFY_SYSTEM, state["query"], prompts.CLASSIFY_SCHEMA)
    _add_tokens(state, usage)

    prefs = state.get("preferences") or {}
    profile = state.get("profile") or {}

    state["on_topic"] = parsed.get("on_topic", True)
    state["safety_concern"] = parsed.get("safety_concern", "")
    state["intent"] = parsed.get("intent", "single_transaction")
    state["spend_items"] = parsed.get("spend_items", []) or []

    named = parsed.get("candidate_cards") or []
    if named:
        state["candidate_cards"] = named
    elif profile.get("cards_owned"):
        known = set(list_cards())
        owned = [c for c in profile["cards_owned"] if c in known]
        state["candidate_cards"] = owned or list_cards()
    else:
        state["candidate_cards"] = list_cards()

    state["preferred_reward_type"] = prefs.get("preferred_reward_type") or parsed.get("preferred_reward_type")
    state["points_balance"] = parsed.get("points_balance")

    answered = bool(state["preferred_reward_type"])
    state["needs_clarification"] = bool(parsed.get("needs_clarification")) and not answered
    state["clarification_question"] = parsed.get("clarification_question", "")
    return state


def refusal_node(state: AgentState) -> AgentState:
    state["stage"] = "refusal"
    concern = state.get("safety_concern") or "the request is outside the scope of this assistant"
    state["final_answer"] = (
        "I'm a credit-card rewards optimization assistant, so I can only help with card "
        f"recommendations, reward calculations, and point transfers. I can't help here because {concern}.\n\n"
        "Try asking something like: *\"I'm spending ₹50,000 on flights — which of my cards should I use?\"*"
    )
    state["halted"] = True
    state["confidence"] = "n/a"
    state["guardrail"] = {"passed": True, "reason": "Off-topic / unsafe input refused by input guardrail."}
    return state


def clarify_node(state: AgentState) -> AgentState:
    """Human-in-the-loop: pause and ask a clarifying question, resume with the user's answer."""
    state["stage"] = "clarify"
    question = state.get("clarification_question") or \
        "Are you optimizing for cashback, airline miles, or hotel points?"
    answer = interrupt({"kind": "clarification", "question": question})
    # `answer` is the value passed on resume (Command(resume=...)).
    state["preferred_reward_type"] = str(answer).strip() if answer else state.get("preferred_reward_type")
    prefs = dict(state.get("preferences") or {})
    prefs["preferred_reward_type"] = state["preferred_reward_type"]
    state["preferences"] = prefs
    state["needs_clarification"] = False
    return state


# --------------------------------------------------------------------------- #
# Node 4: retrieval (RAG chunks + structured rules + transfer partners)
# --------------------------------------------------------------------------- #
def retrieve_node(state: AgentState) -> AgentState:
    state["stage"] = "retrieve"
    cards = state["candidate_cards"]
    categories = [i["category"] for i in state.get("spend_items", [])] or ["general", "travel"]
    rag_query = state["query"] + " " + " ".join(categories)

    state["retrieved_chunks"] = retrieve(rag_query, cards=cards)
    state["effective_dates"] = effective_dates_for(cards)

    rules: List[Dict] = []
    for cat in set(categories):
        for card in cards:
            r = fetch_rule(card, cat)
            if r:
                rules.append(r)
    state["rules"] = rules

    if state["intent"] == "transfer":
        ptype = None
        pref = (state.get("preferred_reward_type") or "").lower()
        if "hotel" in pref:
            ptype = "hotel"
        elif "air" in pref or "flight" in pref or "mile" in pref:
            ptype = "airline"
        state["transfer_partners"] = fetch_transfer_partners(cards=cards, partner_type=ptype)
    return state


# --------------------------------------------------------------------------- #
# Node 5: rule validation
# --------------------------------------------------------------------------- #
def validate_node(state: AgentState) -> AgentState:
    state["stage"] = "validate"
    v = validate_evidence(state.get("retrieved_chunks", []), state.get("rules", []))
    state["validation"] = v
    state["confidence"] = v["confidence"]
    return state


def insufficient_node(state: AgentState) -> AgentState:
    state["stage"] = "insufficient"
    reason = state.get("validation", {}).get("reason", "Not enough grounded evidence.")
    state["final_answer"] = (
        "I don't have enough reliable information in the card documents to make a confident "
        f"recommendation for this query. {reason}\n\nPlease provide the specific card(s) or "
        "spend category, or check the issuer's current terms.\n\n_This is informational, not "
        "certified financial advice._"
    )
    state["halted"] = True
    state["recommended_card"] = None
    state["estimated_value"] = None
    state["guardrail"] = {"passed": True, "reason": "Honest insufficient-information response."}
    return state


# --------------------------------------------------------------------------- #
# Node 6+7: calculation, comparison & per-category allocation
# --------------------------------------------------------------------------- #
def _point_value_override(state: AgentState):
    prefs = state.get("preferences") or {}
    pv = prefs.get("point_valuation")
    return float(pv) if pv else None


def compute_node(state: AgentState) -> AgentState:
    state["stage"] = "compute"
    if state["intent"] == "transfer":
        return _compute_transfer(state)

    cards = state["candidate_cards"]
    spend_items = state.get("spend_items", []) or [{"category": "general", "amount": 0}]
    pv_override = _point_value_override(state)

    calculations: List[Dict] = []
    totals: Dict[str, Dict] = {c: {"card_name": c, "total_value": 0.0, "breakdown": []} for c in cards}
    per_category: Dict[str, List[Dict]] = {}

    for item in spend_items:
        cat, amount = item["category"], float(item["amount"])
        for card in cards:
            rule = fetch_rule(card, cat)
            if not rule:
                continue
            if pv_override is not None and (rule.get("reward_type") != "cashback"):
                rule = {**rule, "point_value": pv_override}
            res = compute_for_rule(amount, rule)
            res["spend_category"] = cat
            calculations.append(res)
            totals[card]["total_value"] += res["reward_value"]
            totals[card]["breakdown"].append(res)
            per_category.setdefault(cat, []).append(res)

    card_totals = sorted(totals.values(), key=lambda t: t["total_value"], reverse=True)
    for t in card_totals:
        t["total_value"] = round(t["total_value"], 2)

    # Per-category best card (monthly optimization).
    allocation = []
    for cat, results in per_category.items():
        best = max(results, key=lambda r: r["reward_value"])
        allocation.append({
            "category": cat,
            "best_card": best["card_name"],
            "value": best["reward_value"],
            "excluded_everywhere": all(r["excluded"] for r in results),
        })

    state["calculations"] = calculations
    state["card_totals"] = card_totals
    state["allocation"] = allocation
    if card_totals:
        state["recommended_card"] = card_totals[0]["card_name"]
        state["estimated_value"] = card_totals[0]["total_value"]
    state["needs_approval"] = False
    return state


def _compute_transfer(state: AgentState) -> AgentState:
    points = float(state.get("points_balance") or 0)
    partners = state.get("transfer_partners", [])
    pv = _point_value_override(state) or DEFAULT_POINT_VALUE
    options = compare_transfers(points, partners, partner_value=pv)
    state["transfer_options"] = options
    if options:
        state["recommended_card"] = options[0]["partner_name"]
        state["estimated_value"] = options[0].get("estimated_value")
    state["needs_approval"] = not state.get("approval_granted", False)
    return state


def approval_node(state: AgentState) -> AgentState:
    """Human-in-the-loop gate before an irreversible transfer recommendation."""
    state["stage"] = "approval"
    pref = state.get("preferred_reward_type") or "your target redemption"
    prompt = (
        "Point transfers are usually irreversible. Confirm you want me to calculate a final "
        f"transfer route using the currently retrieved partner ratios, assuming your goal is "
        f"**{pref}**. Reply 'yes' to proceed or 'no' to cancel."
    )
    state["approval_prompt"] = prompt
    decision = interrupt({"kind": "approval", "prompt": prompt})
    approved = str(decision).strip().lower() in {"yes", "y", "approve", "approved", "true", "1", "ok"}
    state["approval_granted"] = approved
    state["needs_approval"] = not approved
    return state


def cancelled_node(state: AgentState) -> AgentState:
    state["stage"] = "cancelled"
    state["final_answer"] = (
        "No problem — I won't calculate a transfer route. Point transfers are irreversible, so "
        "it's good to be sure. Ask me again whenever you'd like to compare transfer options.\n\n"
        "_This is informational, not certified financial advice._"
    )
    state["halted"] = True
    state["guardrail"] = {"passed": True, "reason": "User declined the transfer approval gate."}
    return state


# --------------------------------------------------------------------------- #
# Node 10: final answer generation
# --------------------------------------------------------------------------- #
def _render_results(state: AgentState) -> str:
    if state["intent"] == "transfer":
        return "TRANSFER OPTIONS (sorted best first):\n" + json.dumps(
            state.get("transfer_options", []), indent=2, default=str)
    out = "PER-CARD TOTALS (sorted best first):\n" + json.dumps(
        state.get("card_totals", []), indent=2, default=str)
    if state["intent"] == "monthly_optimization":
        out += "\n\nPER-CATEGORY ALLOCATION (best card per category):\n" + json.dumps(
            state.get("allocation", []), indent=2, default=str)
    return out


def generate_node(state: AgentState) -> AgentState:
    state["stage"] = "generate"
    context = format_context(state.get("retrieved_chunks", []))
    results = _render_results(state)
    profile = state.get("profile") or {}
    profile_line = ""
    if profile:
        profile_line = (f"\nUSER PROFILE (memory): owns {profile.get('cards_owned')}, prefers "
                        f"{profile.get('preferred_reward_type')}, point valuation "
                        f"{profile.get('point_valuation')}.\n")

    user = (
        f"USER QUERY:\n{state['query']}\n\n"
        f"INTENT: {state['intent']}\n"
        f"PREFERRED REWARD TYPE: {state.get('preferred_reward_type') or 'not specified'}\n"
        f"CONFIDENCE LEVEL: {state.get('confidence')}\n"
        f"DOCUMENT EFFECTIVE DATES: {json.dumps(state.get('effective_dates', {}), default=str)}\n"
        f"{profile_line}\n"
        f"RETRIEVED CARD DOCUMENT EVIDENCE:\n{context}\n\n"
        f"CALCULATOR RESULTS (authoritative — use these numbers):\n{results}\n\n"
        "Write the grounded recommendation following the required section structure."
    )
    answer, usage = llm.complete(prompts.ANSWER_SYSTEM, user, max_tokens=2000, thinking=True)
    _add_tokens(state, usage)
    state["final_answer"] = answer
    return state


# --------------------------------------------------------------------------- #
# Node 8: guardrail check
# --------------------------------------------------------------------------- #
def guardrail_node(state: AgentState) -> AgentState:
    state["stage"] = "guardrail"
    payload = (
        f"USER QUERY:\n{state['query']}\n\n"
        f"RETRIEVED EVIDENCE (cards):\n{[c['card_name'] for c in state.get('retrieved_chunks', [])]}\n\n"
        f"CALCULATOR RESULTS:\n{_render_results(state)}\n\n"
        f"ASSISTANT DRAFT ANSWER:\n{state.get('final_answer', '')}"
    )
    result, usage = llm.complete_json(prompts.GUARDRAIL_SYSTEM, payload, prompts.GUARDRAIL_SCHEMA)
    _add_tokens(state, usage)
    state["guardrail"] = result or {"passed": True, "reason": "guardrail check unavailable"}
    if not state["guardrail"].get("passed", True):
        state["final_answer"] += (
            "\n\n> ⚠️ Automated guardrail flagged this answer for review: "
            f"{state['guardrail'].get('reason', '')}. Please verify against the issuer's terms."
        )
    return state


# --------------------------------------------------------------------------- #
# Node 11: persist long-term user memory (recommendation logging happens in run_agent,
# which knows the final latency and records the query_id for feedback linkage)
# --------------------------------------------------------------------------- #
def persist_node(state: AgentState) -> AgentState:
    state["stage"] = "persist"
    if not state.get("user_id"):
        return state
    try:
        summary = ""
        try:
            s, usage = llm.complete(
                prompts.SUMMARY_SYSTEM,
                f"Query: {state['query']}\nAnswer: {state.get('final_answer', '')[:800]}",
                max_tokens=120,
            )
            _add_tokens(state, usage)
            summary = s
        except Exception:
            pass
        upsert_profile(
            state["user_id"],
            cards_owned=state.get("candidate_cards"),
            preferred_reward_type=state.get("preferred_reward_type"),
            point_valuation=(state.get("preferences") or {}).get("point_valuation"),
            conversation_summary=summary or None,
        )
    except Exception as exc:
        print(f"[memory] persist failed: {exc}")
    return state
