"""LangGraph workflow assembly + run/resume entry points.

Flow:
  memory_load ─▶ classify ──off-topic?──▶ refusal ─▶ END
                     ├──needs clarification?──▶ clarify ─(interrupt→resume)─▶ retrieve
                     └─▶ retrieve ─▶ validate ──invalid?──▶ insufficient ─▶ END
                                              └─valid─▶ compute ──transfer & not approved?──▶ approval
                                                                 │                    (interrupt→resume)
                                                                 │                       ├─approved─▶ generate
                                                                 │                       └─declined─▶ cancelled ─▶ END
                                                                 └─────────────────────────────────▶ generate
                                              generate ─▶ guardrail ─▶ persist ─▶ END

Human-in-the-loop uses LangGraph `interrupt()` + a checkpointer, so clarify/approval pause the
run and resume with the user's answer on the same thread_id (true multi-turn state).
"""
from __future__ import annotations

import time
import uuid
from functools import lru_cache
from typing import Any, Dict, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from agents import nodes
from agents.state import AgentState
from monitoring.logger import log_recommendation


def _after_classify(state: AgentState) -> str:
    if not state.get("on_topic", True):
        return "refusal"
    return "clarify" if state.get("needs_clarification") else "retrieve"


def _after_validate(state: AgentState) -> str:
    return "compute" if state.get("validation", {}).get("valid") else "insufficient"


def _after_compute(state: AgentState) -> str:
    if state.get("intent") == "transfer" and state.get("needs_approval"):
        return "approval"
    return "generate"


def _after_approval(state: AgentState) -> str:
    return "generate" if state.get("approval_granted") else "cancelled"


@lru_cache(maxsize=1)
def build_graph():
    g = StateGraph(AgentState)
    g.add_node("memory_load", nodes.memory_load_node)
    g.add_node("classify", nodes.classify_node)
    g.add_node("refusal", nodes.refusal_node)
    g.add_node("clarify", nodes.clarify_node)
    g.add_node("retrieve", nodes.retrieve_node)
    g.add_node("validate", nodes.validate_node)
    g.add_node("insufficient", nodes.insufficient_node)
    g.add_node("compute", nodes.compute_node)
    g.add_node("approval", nodes.approval_node)
    g.add_node("cancelled", nodes.cancelled_node)
    g.add_node("generate", nodes.generate_node)
    g.add_node("guardrail", nodes.guardrail_node)
    g.add_node("persist", nodes.persist_node)

    g.add_edge(START, "memory_load")
    g.add_edge("memory_load", "classify")
    g.add_conditional_edges("classify", _after_classify,
                            {"refusal": "refusal", "clarify": "clarify", "retrieve": "retrieve"})
    g.add_edge("refusal", END)
    g.add_edge("clarify", "retrieve")
    g.add_edge("retrieve", "validate")
    g.add_conditional_edges("validate", _after_validate,
                            {"compute": "compute", "insufficient": "insufficient"})
    g.add_edge("insufficient", END)
    g.add_conditional_edges("compute", _after_compute,
                            {"approval": "approval", "generate": "generate"})
    g.add_conditional_edges("approval", _after_approval,
                            {"generate": "generate", "cancelled": "cancelled"})
    g.add_edge("cancelled", END)
    g.add_edge("generate", "guardrail")
    g.add_edge("guardrail", "persist")
    g.add_edge("persist", END)

    return g.compile(checkpointer=MemorySaver())


def _extract_interrupt(result: Dict[str, Any]):
    """Return the interrupt payload dict if the run paused for human input, else None."""
    intr = result.get("__interrupt__")
    if not intr:
        return None
    first = intr[0] if isinstance(intr, (list, tuple)) else intr
    return getattr(first, "value", None) or None


def _finalize(result: Dict[str, Any], *, thread_id: str, query: str,
              user_id: Optional[str], latency_ms: int, log: bool) -> AgentState:
    payload = _extract_interrupt(result)
    if payload is not None:
        # Paused for human input — surface it, do not log as a final recommendation.
        result["thread_id"] = thread_id
        result["latency_ms"] = latency_ms
        result["interrupted"] = True
        result["query"] = result.get("query", query)
        if payload.get("kind") == "clarification":
            result["needs_clarification"] = True
            result["clarification_question"] = payload.get("question", "")
        elif payload.get("kind") == "approval":
            result["needs_approval"] = True
            result["approval_prompt"] = payload.get("prompt", "")
        return result  # type: ignore[return-value]

    result["thread_id"] = thread_id
    result["latency_ms"] = latency_ms
    result["interrupted"] = False
    if log:
        try:
            qid = log_recommendation(
                user_id=user_id,
                query_text=query,
                intent=result.get("intent", "unknown"),
                retrieved_chunks=result.get("retrieved_chunks", []),
                recommended_card=result.get("recommended_card"),
                estimated_value=result.get("estimated_value"),
                confidence=result.get("confidence", "n/a"),
                guardrail_passed=bool(result.get("guardrail", {}).get("passed", True)),
                latency_ms=latency_ms,
                input_tokens=result.get("input_tokens", 0),
                output_tokens=result.get("output_tokens", 0),
                final_answer=result.get("final_answer", ""),
            )
            result["query_id"] = qid
        except Exception as exc:  # logging must never break the response
            print(f"[monitoring] failed to log: {exc}")
    return result  # type: ignore[return-value]


def _config(thread_id: str) -> Dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def run_agent(query: str, *, user_id: Optional[str] = None, thread_id: Optional[str] = None,
              preferences: Optional[Dict[str, Any]] = None, approval_granted: bool = False,
              log: bool = True) -> AgentState:
    """Start a new agent run. May pause (interrupted=True) for clarification/approval."""
    graph = build_graph()
    # A fresh thread per run (unless the caller pins one for resume). The checkpointer thread is
    # per-conversation; long-term personalization lives in user_profiles, not the thread state.
    tid = thread_id or f"run-{uuid.uuid4().hex[:12]}"
    initial: AgentState = {
        "query": query,
        "user_id": user_id,
        "thread_id": tid,
        "preferences": preferences or {},
        "approval_granted": approval_granted,
        "input_tokens": 0,
        "output_tokens": 0,
        "halted": False,
    }
    start = time.time()
    result = graph.invoke(initial, config=_config(tid))
    return _finalize(result, thread_id=tid, query=query, user_id=user_id,
                     latency_ms=int((time.time() - start) * 1000), log=log)


def resume_agent(value: Any, *, thread_id: str, user_id: Optional[str] = None,
                 log: bool = True) -> AgentState:
    """Resume a paused run (after clarification answer or approval decision)."""
    graph = build_graph()
    start = time.time()
    result = graph.invoke(Command(resume=value), config=_config(thread_id))
    # Recover the original query from the checkpointed state for logging.
    query = result.get("query", "")
    return _finalize(result, thread_id=thread_id, query=query, user_id=user_id,
                     latency_ms=int((time.time() - start) * 1000), log=log)
