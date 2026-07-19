# Capstone Project: Requirement → Implementation Map
### Intelligent Credit Card & Rewards Optimization Agent

> **Purpose of this document:** Maps every requirement from the capstone PDF to the exact file and function where it is implemented.

---

## 1. What the Project Does (The One-Liner)

A user asks: *"I am spending ₹50,000 on flights. I have Axis Atlas, HDFC DCB, and SBI Cashback. Which card should I use?"*

The system does **not** answer from memory. It:

1. Retrieves the correct reward rules from a vector database (RAG)
2. Validates that the evidence is strong enough to act on
3. Calls a deterministic calculator tool (no LLM math)
4. Compares all eligible cards
5. Runs a guardrail check to ensure the answer is grounded
6. Returns an explainable recommendation with calculation, assumptions, caps, and confidence

---

## 2. Tech Stack — PDF Requirement vs What Is Built

| PDF Recommended | What Is Built | File |
|---|---|---|
| Python + FastAPI | FastAPI REST API | `backend/main.py` |
| LangGraph orchestration | Full stateful graph with MemorySaver checkpointer | `agents/graph.py` |
| PostgreSQL + pgvector | All data in PostgreSQL; vector search via pgvector | `database/db.py`, `database/schema.sql` |
| SQLAlchemy ORM | ORM models for user_profiles and feedback | `database/models.py` |
| PyMuPDF for PDF parsing | `pymupdf` used in `extract_pages()` | `rag/ingest_pdfs.py` |
| Local embedding model | BAAI/bge-small-en-v1.5 via fastembed; hashing fallback | `rag/embeddings.py` |
| Hybrid keyword + vector search | Vector cosine + +0.03 keyword boost, re-ranked | `rag/retrieval.py` |
| LangGraph HITL node | `interrupt()` used in clarify + approval nodes | `agents/nodes.py` |
| Streamlit UI | Full demo UI with HITL buttons, monitoring dashboard | `app/streamlit_app.py` |
| OpenAI / Gemini / local LLM | LiteLLM wrapper — switch provider in `.env` | `llm.py` |
| Custom PostgreSQL monitoring | Logs every query with latency, tokens, result | `monitoring/logger.py` |
| RAGAS / custom evaluation | 4 evaluation scripts covering retrieval, calculation, hallucination | `evaluation/` |

**Current configuration:** `gemini/gemini-2.5-flash` via Gemini free tier. Switch to any provider by changing `LLM_MODEL` in `.env`.

---

## 3. Data Sources (5 Cards Loaded)

| Card | File in `data/cards/` |
|---|---|
| Axis Atlas | `axis_atlas.md` |
| HDFC Diners Club Black | `hdfc_diners_club_black.md` |
| HDFC Infinia | `hdfc_infinia.md` |
| American Express Platinum Travel | `amex_platinum_travel.md` |
| SBI Cashback | `sbi_cashback.md` |

**Current DB state:** 5 card documents · 55 reward rules · 0 user profiles (created on first use)

Rules are **not hardcoded in prompts**. They are extracted by an LLM from the card documents (`rag/extract_rules.py`) and stored in the `reward_rules` table. The LLM only sees them at query time via retrieval.

---

## 4. Database Tables — PDF Spec vs Actual Columns

### Table 1: `card_documents` — Document metadata
`document_id`, `card_name`, `issuer`, `document_type`, `effective_date`, `source_url`, `uploaded_at`

### Table 2: `document_chunks` — RAG vector store
`chunk_id`, `document_id`, `card_name`, `chunk_text`, `page_number`, `embedding` (vector 384-dim), `metadata_json`

### Table 3: `reward_rules` — Structured extracted rules
`rule_id`, `card_name`, `spend_category`, `reward_rate`, `reward_unit`, `cap_type`, `cap_value`, `exclusion_flag`, `milestone_flag`, `source_chunk_id`, `confidence_score`

### Table 4: `transfer_partners` — Point transfer rules
`partner_id`, `card_name`, `partner_name`, `partner_type`, `transfer_ratio`, `minimum_points`, `maximum_points`, `effective_date`, `source_chunk_id`

### Table 5: `user_profiles` — Memory and personalization
`user_id`, `cards_owned`, `preferred_reward_type`, `point_valuation`, `monthly_spend_pattern`, `preferred_partners`, `conversation_summary`

### Table 6: `recommendation_logs` — Monitoring
`query_id`, `user_id`, `query_text`, `retrieved_chunks`, `recommended_card`, `estimated_value`, `confidence_score`, `latency_ms`, `token_usage`, `created_at`

---

## 5. System Architecture — 5 Layers

### Layer 1: Data Ingestion

```
PDF / Markdown file
        │
        ▼
extract_pages()          ← rag/ingest_pdfs.py  (PyMuPDF)
        │
        ▼
chunk_text()             ← rag/ingest_pdfs.py  (900 chars, 150 overlap)
        │
        ▼
embed_texts()            ← rag/embeddings.py   (fastembed / hashing)
        │
        ▼
INSERT document_chunks   ← rag/ingest_pdfs.py  (pgvector IVFFlat index)
        │
        ▼
extract_card()           ← rag/extract_rules.py (LLM extracts structured rules)
        │
        ▼
INSERT reward_rules      ← database (55 rules for 5 cards)
```

**Entry point:** `seed.py` → `make seed` runs the full pipeline once.
**Dynamic add from UI:** `rag/add_card.py` → `add_card_from_pdf()` or `add_card_from_web()`

---

### Layer 2: Retrieval (Hybrid)

File: `rag/retrieval.py` → `retrieve()`

```
User query
     │
     ▼
embed_query()            ← rag/embeddings.py
     │
     ▼
cosine distance SQL      ← pgvector  (SELECT ... ORDER BY embedding <=> $1)
     │
     ▼
keyword boost            ← +0.03 per keyword hit, re-ranked
     │
     ▼
top-K chunks returned    ← default top_k=6

Parallel SQL lookups:
  fetch_rule()           ← tools/retriever.py  (reward_rules table, per card+category)
  fetch_transfer_partners() ← tools/retriever.py (transfer_partners table)
```

Both unstructured (vector) and structured (SQL) retrieval run together in `retrieve_node`.

---

### Layer 3: Agent Reasoning — LangGraph Graph

File: `agents/graph.py` → `build_graph()`

```
START
  │
  ▼
[memory_load]   ← loads user profile from DB
  │
  ▼
[classify]      ← LLM: parses intent, spend items, card names, safety flags
  │
  ├─ off-topic / injection ──► [refusal] ──► END
  ├─ needs_clarification ───► [clarify] ──► (interrupt — waits for user) ──► [retrieve]
  └─ on-topic ──────────────► [retrieve]
                                  │
                               [validate]
                                  │
                     ├─ invalid ─► [insufficient] ──► END
                     └─ valid ──► [compute]
                                     │
                          ├─ transfer ──► [approval] ──► (interrupt — waits for user)
                          │                   ├─ yes ──► [generate]
                          │                   └─ no  ──► [cancelled] ──► END
                          └─ other ──────────► [generate]
                                                   │
                                               [guardrail]
                                                   │
                                               [persist]   ← upserts user profile
                                                   │
                                                 END
```

Every box is a function in `agents/nodes.py`. Routing logic is in `_after_classify`, `_after_validate`, `_after_compute`, `_after_approval` in `agents/graph.py`.

---

### Layer 4: Tool Use (Deterministic — No LLM Math)

**PDF requirement:** *"The agent should NOT do calculations inside the LLM response. It should call a calculator tool."*

#### Calculator Tool — `tools/calculator.py`

```python
# Input (from reward_rules row):
spend = 50000
reward_rate = 5         # points per reward_per_amount
reward_per_amount = 100 # per ₹100
point_value = 1.0       # ₹1 per point
monthly_cap = 5000      # max points

# Output:
units_earned     = 2500
reward_value_rs  = 2500.0
cap_applied      = False
excluded         = False
effective_return = 5.0%   # (reward_value / spend * 100)
```

`compute_for_rule()` unpacks a DB row and calls `compute_reward()`.
`compute_node` in `agents/nodes.py` iterates every **spend item × card**, builds `allocation` and `card_totals`.

#### Transfer Calculator — `tools/transfer_calculator.py`

```python
# Input:
points = 40000
transfer_ratio = 2.0   # 2 partner units per 1 reward point
minimum_points = 1000

# Output:
partner_units_out = 80000
transfer_valid    = True
```

`compare_transfers()` ranks all partners by output value.

#### Rule Validator — `tools/rule_validator.py`

`validate_evidence()` hard-stops the graph if:
- No chunk scores above `MIN_SIMILARITY = 0.30`
- No structured rules were retrieved

This ensures the agent says "I don't have enough information" instead of guessing.

---

### Layer 5: Final Recommendation

The `ANSWER_SYSTEM` prompt in `agents/prompts.py` mandates this exact output structure:

```
## Recommended Card
## Estimated Reward Value
## How the Calculation Was Done
## Rules Used (with source citations)
## Caps and Exclusions
## Assumptions
## Alternative Option
## Confidence Level
```

The LLM cannot deviate — the prompt forbids inventing numbers and requires citing retrieved chunks by index.

---

## 6. LangGraph Nodes — Every Node Mapped

| Node | File → Function | What It Does |
|---|---|---|
| `memory_load` | `nodes.py → memory_load_node` | Loads user profile from `user_profiles` table, seeds preferences into state |
| `classify` | `nodes.py → classify_node` | LLM call with `CLASSIFY_SCHEMA` — extracts intent, spend items, card names, safety flags |
| `refusal` | `nodes.py → refusal_node` | Canned message for off-topic / prompt injection attempts |
| `clarify` | `nodes.py → clarify_node` | `interrupt()` — graph pauses, question surfaces to UI/CLI; resumes with user answer |
| `retrieve` | `nodes.py → retrieve_node` | Hybrid RAG + SQL rules + transfer partners all run here |
| `validate` | `nodes.py → validate_node` | Calls `rule_validator.validate_evidence()` — sets `validation.valid` and `confidence` |
| `insufficient` | `nodes.py → insufficient_node` | Emits "not enough information" message, halts graph |
| `compute` | `nodes.py → compute_node` | Loops spend × card, calls `compute_for_rule()`, builds allocation table + totals |
| `approval` | `nodes.py → approval_node` | `interrupt()` — shows approve/cancel buttons in UI for transfer decisions |
| `cancelled` | `nodes.py → cancelled_node` | Emits cancellation message when user declines transfer |
| `generate` | `nodes.py → generate_node` | Final grounded LLM answer; extended thinking enabled for Anthropic provider |
| `guardrail` | `nodes.py → guardrail_node` | Post-generation LLM review: groundedness, caps mentioned, safe framing, disclaimer |
| `persist` | `nodes.py → persist_node` | Summarises conversation, upserts user profile for next session memory |

---

## 7. Prompting Strategy — All System Prompts

File: `agents/prompts.py`

| Prompt Constant | Used In Node | Purpose |
|---|---|---|
| `CLASSIFY_SYSTEM` + `CLASSIFY_SCHEMA` | `classify_node` | JSON-structured intent parsing; detects injection attempts via `on_topic` flag |
| `ANSWER_SYSTEM` | `generate_node` | Forces grounded, structured answer; forbids inventing numbers; mandates assumptions section |
| `GUARDRAIL_SYSTEM` + `GUARDRAIL_SCHEMA` | `guardrail_node` | Verifies: grounded, no hallucinated rates, caps mentioned, exclusions mentioned, safe framing, disclaimer present |
| `SUMMARY_SYSTEM` | `persist_node` | Extracts durable user facts (cards owned, preferences) for memory storage |
| `EXTRACT_SYSTEM` + `EXTRACT_SCHEMA` | `rag/extract_rules.py` | LLM extracts structured reward rules from document chunks into the `reward_rules` table |

---

## 8. Memory (User Profiles)

**How it works end-to-end:**

1. User enters a `user_id` in the Streamlit sidebar (e.g., `alice`)
2. `memory_load_node` fetches their profile from `user_profiles`
3. Known cards and preferences seed the `classify_node` context
4. After the conversation, `persist_node` calls an LLM to summarise durable facts
5. `upsert_profile()` in `database/models.py` writes them back to DB
6. Next session: the agent already knows "Alice owns Axis Atlas, prefers airline miles"

**What is remembered:** cards_owned, preferred_reward_type, point_valuation, monthly_spend_pattern, preferred_partners, conversation_summary

---

## 9. Human-in-the-Loop (HITL)

The PDF specifies two HITL scenarios. Both use LangGraph's `interrupt()` mechanism:

### Scenario 1: Clarification
- **When:** Intent is clear but preferences are missing (e.g., "optimize for cashback or miles?")
- **Node:** `clarify_node` in `agents/nodes.py`
- **UI:** Streamlit shows a text input box; user types answer; `resume_agent()` called with that answer
- **API:** `POST /resume` with `{"thread_id": "...", "value": "hotel points"}`

### Scenario 2: Transfer Approval
- **When:** User asks about point transfers (irreversible in most programs)
- **Node:** `approval_node` in `agents/nodes.py`
- **UI:** Streamlit shows green "Approve" and red "Cancel" buttons
- **Graph behavior:** The graph literally cannot proceed to `generate` without an explicit yes/no
- **API:** Same `POST /resume` with `{"value": "yes"}` or `{"value": "no"}`

Both interrupts are surfaced to the frontend via the `interrupted`, `needs_clarification`, and `needs_approval` flags in the `AgentState`.

---

## 10. Guardrail Checks — Every Rule from PDF

| PDF Guardrail Rule | Where Enforced | How |
|---|---|---|
| Do not answer without retrieved evidence | `validate_node` + `rule_validator.py` | Hard routing: if `valid=false` → `insufficient_node`, graph ends |
| Do not invent reward rates | `ANSWER_SYSTEM` prompt + `GUARDRAIL_SYSTEM` post-check | Prompt forbids it; guardrail LLM verifies after generation |
| Do not invent transfer partners | `ANSWER_SYSTEM` + `GUARDRAIL_SYSTEM` | Same dual enforcement |
| Do not ignore exclusions | `compute_node` sets `excluded=True` flag; `ANSWER_SYSTEM` mandates mentioning it | Calculator flags exclusions; prompt forces mention |
| Do not ignore caps | `compute_node` sets `cap_applied=True` flag | Calculator flags caps; prompt forces mention |
| Do not present as financial advice | `GUARDRAIL_SCHEMA` `safe_framing` field | Guardrail LLM checks; appends warning to answer if false |
| Mention effective date | `effective_dates_for()` in `tools/retriever.py` | Pulled into retrieve context automatically |
| Ask approval before complex transfers | `approval_node` with `interrupt()` | Structural — graph cannot route past this node without user input |

---

## 11. Monitoring Dashboard

File: `monitoring/logger.py`

Every completed recommendation is logged to `recommendation_logs` with:

| Logged Field | Source |
|---|---|
| `query_text` | User's original question |
| `intent` | Output of `classify_node` |
| `retrieved_chunk_ids` | Chunk IDs from `retrieve_node` |
| `recommended_card` | Best card from `compute_node` |
| `estimated_value` | Calculator output |
| `confidence_score` | From `validate_node` |
| `guardrail_result` | Pass/fail from `guardrail_node` |
| `latency_ms` | Wall clock, start to finish |
| `output_tokens` | From LLM response metadata |
| `final_answer` | Full markdown answer |

**Visible in UI:** Streamlit sidebar shows the last 8 queries with avg latency, avg tokens, feedback ratio.

**API endpoint:** `GET /logs` returns recent logs.

---

## 12. Evaluation — 4 Scripts

Run with: `make eval`

### A. Retrieval Evaluation — `evaluation/rag_eval.py`
- Reads `retrieval_labels.csv` (query → expected card)
- Calls `retrieve()` for each query
- Computes **Precision@K**, **Recall@K**, **MRR**

### B. Calculation Evaluation — `evaluation/calculation_eval.py`
- Reads `calculation_cases.csv` (spend + rate + cap → expected value)
- Calls `compute_reward()` for each case
- Checks exact match within ±₹0.01 and ±0.1% return

### C. Hallucination Evaluation — `evaluation/hallucination_eval.py`
- Runs sample queries through the full agent
- Uses an LLM judge (`JUDGE_SYSTEM` / `JUDGE_SCHEMA`) to verify:
  - No invented reward rates
  - No invented cards or partners
  - Numbers match retrieved evidence
- Reports faithful / hallucinated ratio

### D. End-to-End Golden Evaluation — `evaluation/evaluate.py`
- Reads `golden_answers.csv` (query → expected intent + expected card)
- Runs full agent for each
- Checks `intent` and `recommended_card` accuracy

---

## 13. APIs — FastAPI Backend

File: `backend/main.py` — run with `make api` (port 8000)

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | DB ping + list of loaded cards |
| `/ask` | POST | Start a new agent run; may return `interrupted=true` for HITL |
| `/resume` | POST | Resume a paused run with user's clarification or approval |
| `/feedback` | POST | Record thumbs-up / thumbs-down for a query |
| `/cards/add_web` | POST | Ingest a new card by name (agent web-searches the terms) |
| `/cards/add_pdf` | POST | Ingest a new card from uploaded PDF |
| `/logs` | GET | Recent recommendation logs for monitoring |

---

## 14. Interfaces — Three Ways to Use the System

### 1. Streamlit Web UI (primary demo)
```
make ui          # http://localhost:8501
```
Features: sample queries in sidebar, user memory, HITL approval/clarification buttons, monitoring table, dynamic card add.

### 2. CLI (quick testing)
```
make cli         # interactive REPL
python cli.py -q "Which card for flights?"   # one-shot
```
Full multi-turn HITL support in terminal — clarification prompts and approve/cancel appear as text.

### 3. REST API (programmatic)
```
make api         # http://localhost:8000
```
All agent features available as JSON endpoints.

---

## 15. Stage-Wise Delivery — What Was Built

| Stage | PDF Goal | Status | Key Files |
|---|---|---|---|
| **Stage 1** | RAG + basic agent + CLI | Done | `rag/`, `agents/`, `cli.py` |
| **Stage 2** | LangGraph stateful workflow, calculator, memory, multi-turn | Done | `agents/graph.py`, `agents/nodes.py`, `tools/calculator.py`, `persist_node`, `memory_load_node` |
| **Stage 3** | Streamlit UI, HITL, guardrails, monitoring, evaluation | Done | `app/streamlit_app.py`, `approval_node`, `guardrail_node`, `monitoring/logger.py`, `evaluation/` |

---

## 16. How to Run — Quick Reference

```bash
# One-time setup (schema + ingest + seed rules)
make seed

# Launch Streamlit UI
python3 -m streamlit run app/streamlit_app.py

# Or via Makefile (if venv shebangs are intact)
make ui

# Run all tests
make test

# Run evaluations
make eval

# Run FastAPI backend
make api
```

**Environment:** `.env` file in project root sets `LLM_MODEL`, `GEMINI_API_KEY`, `PGDATABASE`, `EMBED_BACKEND`.

---

## 17. Folder Structure — Every Folder Explained

```
capstone-intelligent-credit_card-optimization_agent/
│
├── agents/
│   ├── graph.py        ← LangGraph graph assembly + run_agent / resume_agent
│   ├── nodes.py        ← All 13 node functions
│   ├── prompts.py      ← All system prompts and JSON schemas
│   └── state.py        ← AgentState TypedDict (all graph state keys)
│
├── tools/
│   ├── calculator.py         ← Deterministic reward arithmetic
│   ├── retriever.py          ← SQL lookups: rules, partners, dates
│   ├── rule_validator.py     ← Evidence quality gate
│   └── transfer_calculator.py← Point transfer arithmetic
│
├── rag/
│   ├── ingest_pdfs.py    ← PDF parsing, chunking, embedding, storing
│   ├── embeddings.py     ← Local embed: fastembed or hashing
│   ├── retrieval.py      ← Hybrid vector + keyword search
│   ├── extract_rules.py  ← LLM extracts structured rules from chunks
│   ├── add_card.py       ← Dynamic add from UI (PDF or web search)
│   └── collect_web.py    ← Offline web collector for card data
│
├── database/
│   ├── db.py        ← psycopg3 connection, schema init, ping
│   ├── models.py    ← SQLAlchemy ORM: UserProfile, Feedback, CRUD
│   └── schema.sql   ← All CREATE TABLE statements
│
├── app/
│   └── streamlit_app.py  ← Full Streamlit demo UI
│
├── backend/
│   └── main.py           ← FastAPI endpoints
│
├── monitoring/
│   └── logger.py         ← log_recommendation(), recent_logs()
│
├── evaluation/
│   ├── rag_eval.py           ← Precision@K, Recall@K, MRR
│   ├── calculation_eval.py   ← Exact match calculator tests
│   ├── hallucination_eval.py ← LLM-as-judge faithfulness
│   └── evaluate.py           ← Golden answer end-to-end tests
│
├── tests/
│   ├── test_calculator.py ← Unit tests (no DB / API key needed)
│   └── test_retrieval.py  ← Integration tests (needs seeded DB)
│
├── data/
│   └── cards/             ← 5 card markdown documents + manifest.csv
│
├── llm.py         ← LiteLLM wrapper (provider-agnostic)
├── config.py      ← All settings loaded from .env
├── seed.py        ← One-shot setup: schema + ingest + extract rules
├── cli.py         ← Interactive CLI with HITL support
├── Makefile       ← make ui / cli / api / seed / test / eval
└── .env           ← LLM_MODEL, GEMINI_API_KEY, PGDATABASE, etc.
```

---

*Document generated from project source. All file paths are relative to the project root.*
