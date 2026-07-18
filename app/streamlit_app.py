"""Streamlit demo UI for the Intelligent Credit Card & Rewards Optimization Agent.

Run from the project root:  streamlit run app/streamlit_app.py

Demonstrates: RAG grounding, LangGraph agent, tool-use calculation, per-category allocation,
user memory (profile), human-in-the-loop clarification/approval, guardrails, feedback, monitoring.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import config  # noqa: E402
from agents.graph import resume_agent, run_agent  # noqa: E402
from database.db import ping  # noqa: E402
from database.models import add_feedback, feedback_summary, get_profile  # noqa: E402
from monitoring.logger import recent_logs  # noqa: E402
from rag.add_card import add_card_from_pdf, add_card_from_web  # noqa: E402
from tools.retriever import list_cards  # noqa: E402

st.set_page_config(page_title="Credit Card Rewards Agent", page_icon="💳", layout="wide")
st.title("💳 Intelligent Credit Card & Rewards Optimization Agent")
st.caption("RAG + LangGraph agent + tool-use + memory + guardrails + human approval + monitoring. "
           "Card data is illustrative — not official issuer terms.")

ss = st.session_state
ss.setdefault("result", None)
ss.setdefault("thread_id", None)

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.subheader("Status")
    st.write("Database:", "🟢 connected" if ping() else "🔴 unreachable")
    st.write("Model:", f"`{config.LLM_MODEL}`")
    st.write("LLM ready:", "🟢 yes" if config.llm_ready() else f"🔴 no ({config.LLM_PROVIDER} key missing)")

    st.subheader("User (memory)")
    user_id = st.text_input("user id (optional)", value="", placeholder="e.g. alice") or None
    if user_id:
        prof = get_profile(user_id)
        if prof:
            st.caption(f"Remembered: cards={prof.get('cards_owned')}, "
                       f"prefers={prof.get('preferred_reward_type')}")

    with st.expander("➕ Add a card to the knowledge base"):
        st.caption(f"Known cards: {', '.join(list_cards())}")
        mode = st.radio("Source", ["Search web by name", "Upload PDF"], key="add_mode")
        if not config.llm_ready():
            st.info(f"Needs the {config.LLM_PROVIDER} key (web search + rule extraction).")
        if mode == "Search web by name":
            cname = st.text_input("Card name", placeholder="e.g. ICICI Amazon Pay", key="web_card")
            ciss = st.text_input("Issuer (optional)", key="web_issuer")
            if st.button("Search & add", key="btn_web") and cname.strip():
                with st.spinner("Claude is web-searching and structuring the card…"):
                    try:
                        res = add_card_from_web(cname.strip(), ciss.strip() or None)
                        st.success(f"Added {res['card_name']}: {res['chunks']} chunks, "
                                   f"{res['reward_rules']} rules, {res['transfer_partners']} partners.")
                    except Exception as exc:
                        st.error(f"Failed: {exc}")
        else:
            cname = st.text_input("Card name", placeholder="e.g. HDFC Regalia", key="pdf_card")
            ciss = st.text_input("Issuer (optional)", key="pdf_issuer")
            up = st.file_uploader("Card terms PDF", type=["pdf"], key="pdf_up")
            if st.button("Upload & add", key="btn_pdf") and cname.strip() and up is not None:
                with st.spinner("Ingesting PDF and extracting structured rules…"):
                    try:
                        res = add_card_from_pdf(up.read(), cname.strip(), ciss.strip() or None)
                        st.success(f"Added {res['card_name']}: {res['chunks']} chunks, "
                                   f"{res['reward_rules']} rules, {res['transfer_partners']} partners.")
                    except Exception as exc:
                        st.error(f"Failed: {exc}")

    st.subheader("Try a sample query")
    samples = [
        "I am booking a Rs 50,000 domestic flight. I have Axis Atlas, HDFC Diners Club Black, and SBI Cashback. Which card should I use?",
        "My monthly spends are Rs 30,000 on dining, Rs 40,000 on travel, Rs 20,000 on groceries, and Rs 15,000 on utilities. Suggest the best card-wise allocation.",
        "I have 40,000 reward points on Axis Atlas. Should I transfer them to hotel partners or airline partners?",
        "Which card is best for rent payment?",
    ]
    for s in samples:
        if st.button(s, key=f"sample_{hash(s)}", use_container_width=True):
            ss["query_input"] = s        # prefill the (keyed) input box
            st.rerun()

    st.subheader("Monitoring")
    try:
        logs = recent_logs(8)
        if logs:
            df = pd.DataFrame(logs)
            st.caption(f"avg latency: {df['latency_ms'].mean():.0f} ms · "
                       f"avg out-tokens: {df['output_tokens'].mean():.0f} · feedback: {feedback_summary()}")
            st.dataframe(df[["query_id", "intent", "recommended_card", "estimated_value",
                             "confidence", "latency_ms", "output_tokens"]],
                         hide_index=True, use_container_width=True)
    except Exception as exc:
        st.write(f"(logs unavailable: {exc})")

# ---------------------------------------------------------------- input
ss.setdefault("query_input", "")
# keyed widget -> the text persists across reruns (not cleared while a query runs)
query = st.text_area("Ask about a transaction, monthly spends, or a point transfer:",
                     key="query_input", height=90)
pref = st.text_input("Optional preference", placeholder="hotel points / airline miles / cashback")

if st.button("Ask", type="primary") and query.strip():
    if not config.llm_ready():
        st.error(f"LLM not configured for provider '{config.LLM_PROVIDER}' ({config.LLM_MODEL}). Set the key/LLM_MODEL in .env and restart.")
    else:
        ss["thread_id"] = f"ui-{uuid.uuid4().hex[:8]}"
        prefs = {"preferred_reward_type": pref.strip()} if pref.strip() else None
        with st.status("Working on your query… (~20–40s on free-tier Gemini)", expanded=True) as status:
            st.write("🔎 Retrieving card rules (RAG) …")
            st.write("🧮 Running the reward calculator …")
            st.write("🧠 Reasoning + guardrail check …")
            try:
                ss["result"] = run_agent(query, user_id=user_id, thread_id=ss["thread_id"], preferences=prefs)
                status.update(label="Done ✓", state="complete", expanded=False)
            except Exception as exc:
                ss["result"] = None
                status.update(label="Failed", state="error")
                st.error(f"LLM call failed ({type(exc).__name__}). On free-tier Gemini this is "
                         f"usually a rate limit — wait a moment and retry. Details: {str(exc)[:300]}")


# ---------------------------------------------------------------- render
def render(result: dict, user_id) -> None:
    # Human-in-the-loop: clarification
    if result.get("interrupted") and result.get("needs_clarification"):
        st.info(f"**Clarification needed:** {result.get('clarification_question')}")
        ans = st.text_input("Your answer", key="clarify_ans")
        if st.button("Send answer") and ans.strip():
            with st.spinner("Continuing…"):
                ss["result"] = resume_agent(ans.strip(), thread_id=result["thread_id"], user_id=user_id)
            st.rerun()
        return

    # Human-in-the-loop: approval gate
    if result.get("interrupted") and result.get("needs_approval"):
        st.warning(result.get("approval_prompt", "Approve this irreversible transfer calculation?"))
        c1, c2 = st.columns(2)
        if c1.button("✅ Approve"):
            with st.spinner("Calculating transfer route…"):
                ss["result"] = resume_agent("yes", thread_id=result["thread_id"], user_id=user_id)
            st.rerun()
        if c2.button("❌ Cancel"):
            with st.spinner("Cancelling…"):
                ss["result"] = resume_agent("no", thread_id=result["thread_id"], user_id=user_id)
            st.rerun()
        return

    # Final answer
    st.markdown(result.get("final_answer", "(no answer)"))

    cols = st.columns(4)
    cols[0].metric("Recommended", result.get("recommended_card") or "—")
    val = result.get("estimated_value")
    cols[1].metric("Est. value", f"Rs {val:,.0f}" if val is not None else "—")
    cols[2].metric("Confidence", result.get("confidence", "—"))
    cols[3].metric("Latency", f"{result.get('latency_ms', 0)} ms")

    if result.get("allocation"):
        with st.expander("🧭 Per-category allocation", expanded=True):
            st.dataframe(pd.DataFrame(result["allocation"]), hide_index=True, use_container_width=True)

    if result.get("card_totals"):
        with st.expander("📊 Per-card totals"):
            st.dataframe(pd.DataFrame([{"Card": t["card_name"], "Total value (Rs)": t["total_value"]}
                                       for t in result["card_totals"]]),
                         hide_index=True, use_container_width=True)

    if result.get("transfer_options"):
        with st.expander("🔁 Transfer options", expanded=True):
            st.dataframe(pd.DataFrame(result["transfer_options"]), hide_index=True, use_container_width=True)

    with st.expander("🔎 Retrieved evidence (RAG) & guardrail"):
        for c in result.get("retrieved_chunks", []):
            st.markdown(f"**{c['card_name']}** · page {c['page_number']} · relevance {c['score']:.2f}")
            st.caption(c["chunk_text"][:400] + ("…" if len(c["chunk_text"]) > 400 else ""))
        st.json(result.get("guardrail", {}))

    # Feedback (Stage 3)
    qid = result.get("query_id")
    if qid:
        st.write("Was this helpful?")
        f1, f2, _ = st.columns([1, 1, 6])
        if f1.button("👍"):
            add_feedback(qid, user_id, "up"); st.toast("Thanks for the feedback!")
        if f2.button("👎"):
            add_feedback(qid, user_id, "down"); st.toast("Thanks — we'll improve.")


if ss.get("result"):
    render(ss["result"], user_id)
