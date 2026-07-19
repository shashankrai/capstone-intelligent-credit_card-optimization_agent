"""Streamlit chat UI for the Intelligent Credit Card & Rewards Optimization Agent.

Run from the project root:  streamlit run app/streamlit_app.py
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

st.set_page_config(
    page_title="Credit Card Rewards Agent",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded",
)

ss = st.session_state
# ── persistent state ──────────────────────────────────────────────────────────
ss.setdefault("messages", [])      # full chat history: list of message dicts
ss.setdefault("thread_id", None)   # active LangGraph thread (kept alive for HITL resume)

# ─────────────────────────────────────────────────────────────────── sidebar ──
with st.sidebar:
    st.markdown("## 💳 Rewards Agent")

    # Status pills
    db_ok  = ping()
    llm_ok = config.llm_ready()
    col_db, col_llm = st.columns(2)
    col_db.markdown(f"{'🟢' if db_ok  else '🔴'} **DB**")
    col_llm.markdown(f"{'🟢' if llm_ok else '🔴'} **LLM**")
    st.caption(f"`{config.LLM_MODEL}`")

    st.divider()

    # User memory
    st.subheader("User Memory")
    user_id = (
        st.text_input("User ID (optional)", value="", placeholder="e.g. alice",
                      help="Same ID across sessions = remembered preferences")
        or None
    )
    if user_id:
        prof = get_profile(user_id)
        if prof:
            st.caption(
                f"Cards: {prof.get('cards_owned') or '—'}  \n"
                f"Prefers: {prof.get('preferred_reward_type') or '—'}"
            )
        else:
            st.caption("New user — profile saved after first chat.")

    st.divider()

    # Sample queries → inject into chat on click
    st.subheader("Sample Queries")
    st.caption("From capstone project PDF")
    samples = [
        "I am spending Rs 50,000 on flights. Which card should I use?",
        "My monthly spends are Rs 30,000 dining, Rs 40,000 travel, Rs 20,000 groceries, Rs 15,000 utilities. Suggest card-wise allocation.",
        "I have 40,000 Axis Atlas points. Should I transfer them to hotel partners or airline partners?",
        "Which card is best for rent payment?",
        "I am paying Rs 25,000 insurance premium. Which card should I use?",
        "Rs 60,000 online shopping — best card?",
        "Compare Axis Atlas and HDFC Infinia for travel.",
        "I have 80,000 points. Tell me how to transfer them for maximum hotel value.",
    ]
    for s in samples:
        label = (s[:58] + "…") if len(s) > 58 else s
        if st.button(label, key=f"sample_{hash(s)}", use_container_width=True):
            ss["_inject"] = s
            st.rerun()

    st.caption("Verification & edge-case testing")
    verify_samples = [
        # single-transaction edge cases
        "I am spending Rs 30,000 on fuel. Best card?",
        "I have a Rs 80,000 hotel booking. Which card gives the most?",
        "Best card for Rs 20,000 dining spend?",
        "Rs 50,000 flight — I only have SBI Cashback and Amex Platinum Travel. Which?",
        # monthly optimization with exclusion
        "Allocate my monthly spends: Rs 50,000 flights, Rs 25,000 online, Rs 10,000 fuel.",
        # cap boundary test
        "Rs 2,00,000 online spend this month on SBI Cashback — how much cashback?",
        # comparison
        "Which is better for flights: Axis Atlas or SBI Cashback?",
        # user-preference + owned-cards
        "I have Axis Atlas and value hotel points. Rs 70,000 hotel spend — which card?",
        # guardrail: insufficient evidence
        "What is the reward rate for education fee payment?",
        # guardrail: off-topic / refusal
        "What is the best stock to buy right now?",
    ]
    for s in verify_samples:
        label = (s[:58] + "…") if len(s) > 58 else s
        if st.button(label, key=f"verify_{hash(s)}", use_container_width=True):
            ss["_inject"] = s
            st.rerun()

    st.divider()

    # New conversation
    if st.button("🗑  New Conversation", use_container_width=True, type="secondary"):
        ss["messages"] = []
        ss["thread_id"] = None
        st.rerun()

    st.divider()

    # Add a card
    with st.expander("➕ Add a card"):
        st.caption(f"Loaded: {', '.join(list_cards())}")
        mode = st.radio("Source", ["Search web", "Upload PDF"], key="add_mode")
        if not config.llm_ready():
            st.info(f"Needs {config.LLM_PROVIDER} key.")
        if mode == "Search web":
            cname = st.text_input("Card name", placeholder="e.g. ICICI Amazon Pay", key="web_card")
            ciss  = st.text_input("Issuer (optional)", key="web_issuer")
            if st.button("Search & add", key="btn_web") and cname.strip():
                with st.spinner("Searching and structuring…"):
                    try:
                        res = add_card_from_web(cname.strip(), ciss.strip() or None)
                        st.success(f"Added {res['card_name']}: {res['chunks']} chunks, "
                                   f"{res['reward_rules']} rules.")
                    except Exception as exc:
                        st.error(f"Failed: {exc}")
        else:
            cname = st.text_input("Card name", placeholder="e.g. HDFC Regalia", key="pdf_card")
            ciss  = st.text_input("Issuer (optional)", key="pdf_issuer")
            up    = st.file_uploader("Card PDF", type=["pdf"], key="pdf_up")
            if st.button("Upload & add", key="btn_pdf") and cname.strip() and up is not None:
                with st.spinner("Ingesting PDF…"):
                    try:
                        res = add_card_from_pdf(up.read(), cname.strip(), ciss.strip() or None)
                        st.success(f"Added {res['card_name']}: {res['chunks']} chunks, "
                                   f"{res['reward_rules']} rules.")
                    except Exception as exc:
                        st.error(f"Failed: {exc}")

    st.divider()

    # Monitoring
    st.subheader("Monitoring")
    try:
        logs = recent_logs(6)
        if logs:
            df = pd.DataFrame(logs)
            st.caption(
                f"avg {df['latency_ms'].mean():.0f} ms · "
                f"{df['output_tokens'].mean():.0f} tokens · "
                f"{feedback_summary()}"
            )
            st.dataframe(
                df[["query_id", "intent", "recommended_card", "latency_ms"]],
                hide_index=True, use_container_width=True,
            )
        else:
            st.caption("No queries yet.")
    except Exception as exc:
        st.caption(f"logs unavailable: {exc}")


# ───────────────────────────────────────────────────────── helper renderers ──

def _render_result(result: dict, msg_idx: int) -> None:
    """Render a completed agent result inside a chat bubble."""
    st.markdown(result.get("final_answer", "*(no answer)*"))

    # Key metrics
    cols = st.columns(4)
    cols[0].metric("Best card",   result.get("recommended_card") or "—")
    val = result.get("estimated_value")
    cols[1].metric("Est. value",  f"₹{val:,.0f}" if val is not None else "—")
    cols[2].metric("Confidence",  result.get("confidence", "—"))
    cols[3].metric("Latency",     f"{result.get('latency_ms', 0)} ms")

    if result.get("allocation"):
        with st.expander("🧭 Per-category allocation", expanded=True):
            st.dataframe(pd.DataFrame(result["allocation"]),
                         hide_index=True, use_container_width=True)

    if result.get("card_totals"):
        with st.expander("📊 Per-card totals"):
            st.dataframe(
                pd.DataFrame([{"Card": t["card_name"], "Total (₹)": t["total_value"]}
                               for t in result["card_totals"]]),
                hide_index=True, use_container_width=True,
            )

    if result.get("transfer_options"):
        with st.expander("🔁 Transfer options", expanded=True):
            st.dataframe(pd.DataFrame(result["transfer_options"]),
                         hide_index=True, use_container_width=True)

    with st.expander("🔎 Retrieved evidence & guardrail"):
        for c in result.get("retrieved_chunks", []):
            st.markdown(f"**{c['card_name']}** · page {c['page_number']} · score {c['score']:.2f}")
            st.caption(c["chunk_text"][:400] + ("…" if len(c["chunk_text"]) > 400 else ""))
        st.json(result.get("guardrail", {}))

    # Thumbs feedback — keyed by msg index + query_id to survive rerenders
    qid = result.get("query_id")
    if qid:
        f1, f2, _ = st.columns([1, 1, 8])
        if f1.button("👍", key=f"up_{msg_idx}_{qid}"):
            add_feedback(qid, user_id, "up");   st.toast("Thanks!")
        if f2.button("👎", key=f"dn_{msg_idx}_{qid}"):
            add_feedback(qid, user_id, "down"); st.toast("Thanks — we'll improve.")


# ─────────────────────────────────────────────── agent call wrappers ─────────

def _run_new_query(query: str) -> None:
    """Start a brand-new agent run and append the result to chat history."""
    ss["thread_id"] = f"ui-{uuid.uuid4().hex[:8]}"
    with st.spinner("Thinking… (retrieve → calculate → reason → guardrail)"):
        try:
            result = run_agent(query, user_id=user_id, thread_id=ss["thread_id"])
        except Exception as exc:
            ss["messages"].append({
                "role": "assistant", "error": True,
                "content": f"LLM error: {str(exc)[:400]}",
            })
            st.rerun()
            return

    ss["messages"].append({
        "role":                 "assistant",
        "result":               result,
        "interrupted":          result.get("interrupted", False),
        "needs_clarification":  result.get("needs_clarification", False),
        "needs_approval":       result.get("needs_approval", False),
        "clarification_question": result.get("clarification_question", ""),
        "approval_prompt":      result.get("approval_prompt", ""),
    })
    st.rerun()


def _resume(value: str) -> None:
    """Resume a paused (interrupted) agent run."""
    with st.spinner("Continuing…"):
        try:
            result = resume_agent(value, thread_id=ss["thread_id"], user_id=user_id)
        except Exception as exc:
            ss["messages"].append({
                "role": "assistant", "error": True,
                "content": f"Resume error: {str(exc)[:400]}",
            })
            st.rerun()
            return

    ss["messages"].append({
        "role":                 "assistant",
        "result":               result,
        "interrupted":          result.get("interrupted", False),
        "needs_clarification":  result.get("needs_clarification", False),
        "needs_approval":       result.get("needs_approval", False),
        "clarification_question": result.get("clarification_question", ""),
        "approval_prompt":      result.get("approval_prompt", ""),
    })
    st.rerun()


# ───────────────────────────────────────────────────── render chat history ───

# Empty-state splash (only when no messages)
if not ss["messages"]:
    st.markdown(
        """
        <div style="text-align:center;padding:80px 20px 40px;color:#9ca3af;">
          <div style="font-size:52px;margin-bottom:14px">💳</div>
          <div style="font-size:18px;font-weight:700;color:#111827;margin-bottom:8px">
            Ask me anything about credit card rewards
          </div>
          <div style="font-size:13px;color:#6b7280;margin-bottom:6px">
            Single transactions &nbsp;·&nbsp; Monthly spend optimization
            &nbsp;·&nbsp; Point transfers &nbsp;·&nbsp; Card comparison
          </div>
          <div style="font-size:12px;margin-top:18px;color:#9ca3af;">
            Pick a sample query from the sidebar or type below to begin.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Render all messages in order
for i, msg in enumerate(ss["messages"]):
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])

    else:  # assistant
        with st.chat_message("assistant", avatar="💳"):
            if msg.get("error"):
                st.error(msg.get("content", "Unknown error"))

            elif msg.get("interrupted"):
                # Show the pause state — answer will come after user responds
                if msg.get("needs_clarification"):
                    st.info(
                        f"**Clarification needed**\n\n"
                        f"{msg.get('clarification_question', 'Could you provide more details?')}"
                    )
                elif msg.get("needs_approval"):
                    st.warning(
                        msg.get("approval_prompt",
                                "Approve to calculate the transfer route using current partner ratios.")
                    )

            elif msg.get("result"):
                _render_result(msg["result"], i)

            else:
                st.markdown(msg.get("content", ""))


# ───────────────────────────────── HITL widgets or normal chat input ─────────

# Determine whether we're in a HITL pause
last = ss["messages"][-1] if ss["messages"] else None
in_hitl = last and last.get("interrupted") and last["role"] == "assistant"

if in_hitl:
    # ── clarification ─────────────────────────────────────────────────────────
    if last.get("needs_clarification"):
        st.caption("Answer the clarification question above to continue:")
        c1, c2 = st.columns([6, 1])
        ans = c1.text_input(
            "clarify", label_visibility="collapsed",
            placeholder="Type your answer…", key="clarify_input",
        )
        if c2.button("Send ➤", key="clarify_send") and ans.strip():
            ss["messages"].append({"role": "user", "content": ans.strip()})
            _resume(ans.strip())

    # ── approval ──────────────────────────────────────────────────────────────
    elif last.get("needs_approval"):
        st.caption("Approve to calculate the point transfer route:")
        col1, col2, _ = st.columns([1, 1, 5])
        if col1.button("✅ Approve", key="btn_approve", type="primary"):
            ss["messages"].append({"role": "user", "content": "✅ Approved the transfer calculation."})
            _resume("yes")
        if col2.button("❌ Cancel", key="btn_cancel"):
            ss["messages"].append({"role": "user", "content": "❌ Cancelled."})
            _resume("no")

else:
    # ── normal chat input ─────────────────────────────────────────────────────
    # Consume any query injected by a sidebar sample-button click
    injected = None
    if "_inject" in ss:
        injected = ss["_inject"]
        del ss["_inject"]

    prompt = st.chat_input(
        "Ask about a transaction, monthly spends, or point transfers…",
        key="chat_input",
    )

    active = injected or prompt
    if active:
        if not config.llm_ready():
            st.error(
                f"LLM not configured — set {config.LLM_PROVIDER.upper()}_API_KEY "
                f"in .env and restart the app."
            )
        else:
            ss["messages"].append({"role": "user", "content": active})
            _run_new_query(active)
