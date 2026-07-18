"""FastAPI backend exposing the agent + human-in-the-loop resume + feedback + monitoring.

Run:  uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from agents.graph import resume_agent, run_agent
from database.db import ping
from database.models import add_feedback, feedback_summary
from monitoring.logger import recent_logs
from rag.add_card import add_card_from_pdf, add_card_from_web
from tools.retriever import list_cards

app = FastAPI(title="Intelligent Credit Card & Rewards Optimization Agent")


class AskRequest(BaseModel):
    query: str
    user_id: Optional[str] = None
    thread_id: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None
    approval_granted: bool = False


class ResumeRequest(BaseModel):
    thread_id: str
    value: str
    user_id: Optional[str] = None


class FeedbackRequest(BaseModel):
    query_id: Optional[int] = None
    user_id: Optional[str] = None
    rating: str  # 'up' | 'down'
    note: Optional[str] = None


class AddCardWebRequest(BaseModel):
    card_name: str
    issuer: Optional[str] = None


class AgentResponse(BaseModel):
    answer: str
    thread_id: Optional[str] = None
    query_id: Optional[int] = None
    interrupted: bool = False
    intent: str = "unknown"
    recommended_card: Optional[str] = None
    estimated_value: Optional[float] = None
    confidence: str = "n/a"
    needs_approval: bool = False
    needs_clarification: bool = False
    clarification_question: str = ""
    approval_prompt: str = ""
    guardrail: Dict[str, Any] = {}
    card_totals: List[Dict[str, Any]] = []
    allocation: List[Dict[str, Any]] = []
    transfer_options: List[Dict[str, Any]] = []
    retrieved_cards: List[str] = []
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


def _to_response(r: Dict[str, Any]) -> AgentResponse:
    return AgentResponse(
        answer=r.get("final_answer", ""),
        thread_id=r.get("thread_id"),
        query_id=r.get("query_id"),
        interrupted=bool(r.get("interrupted")),
        intent=r.get("intent", "unknown"),
        recommended_card=r.get("recommended_card"),
        estimated_value=r.get("estimated_value"),
        confidence=r.get("confidence", "n/a"),
        needs_approval=bool(r.get("needs_approval")),
        needs_clarification=bool(r.get("needs_clarification")),
        clarification_question=r.get("clarification_question", ""),
        approval_prompt=r.get("approval_prompt", ""),
        guardrail=r.get("guardrail", {}),
        card_totals=r.get("card_totals", []),
        allocation=r.get("allocation", []),
        transfer_options=r.get("transfer_options", []),
        retrieved_cards=sorted({c["card_name"] for c in r.get("retrieved_chunks", [])}),
        latency_ms=r.get("latency_ms", 0),
        input_tokens=r.get("input_tokens", 0),
        output_tokens=r.get("output_tokens", 0),
    )


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "db": ping(), "cards": list_cards()}


@app.post("/ask", response_model=AgentResponse)
def ask(req: AskRequest) -> AgentResponse:
    r = run_agent(req.query, user_id=req.user_id, thread_id=req.thread_id,
                  preferences=req.preferences, approval_granted=req.approval_granted)
    return _to_response(r)


@app.post("/resume", response_model=AgentResponse)
def resume(req: ResumeRequest) -> AgentResponse:
    r = resume_agent(req.value, thread_id=req.thread_id, user_id=req.user_id)
    return _to_response(r)


@app.post("/feedback")
def feedback(req: FeedbackRequest) -> Dict[str, Any]:
    fid = add_feedback(req.query_id, req.user_id, req.rating, req.note)
    return {"feedback_id": fid, "summary": feedback_summary()}


@app.post("/cards/add_web")
def add_card_web(req: AddCardWebRequest) -> Dict[str, Any]:
    """Add a card by name — Claude web-searches its terms, then ingests + extracts structured rules."""
    try:
        return add_card_from_web(req.card_name, req.issuer)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/cards/add_pdf")
async def add_card_pdf(card_name: str = Form(...), issuer: Optional[str] = Form(None),
                       file: UploadFile = File(...)) -> Dict[str, Any]:
    """Add a card from an uploaded PDF — same ingest + extract pipeline as the web path."""
    try:
        data = await file.read()
        return add_card_from_pdf(data, card_name, issuer, source_url=file.filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/logs")
def logs(limit: int = 20) -> List[Dict[str, Any]]:
    return recent_logs(limit)
