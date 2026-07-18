# Intelligent Credit Card & Rewards Optimization Agent

A capstone implementation of an AI agent that recommends the best credit card or reward
strategy for a transaction — grounded in retrieved card documents, with deterministic reward
calculation, per-category allocation, user memory, guardrails, human approval for irreversible
transfers, feedback capture, evaluation, and monitoring.

Implements the full brief: **RAG + LangGraph agent + tool use + memory + guardrails (input &
output) + human-in-the-loop + evaluation + monitoring.**

```
memory_load ─▶ classify ──off-topic/injection?──▶ refusal ─▶ END
                   ├──needs clarification?──▶ clarify ─(interrupt→resume)─▶ retrieve
                   └─▶ retrieve ─▶ validate ──weak evidence?──▶ insufficient ─▶ END
                                            └─valid─▶ compute ──transfer & not approved?──▶ approval
                                                              │                (interrupt→resume)
                                                              │                   ├─approved─▶ generate
                                                              │                   └─declined─▶ cancelled ─▶ END
                                                              └────────────────────────────▶ generate
                                            generate ─▶ guardrail ─▶ persist(memory) ─▶ END
```

## Tech stack

| Layer | Choice |
|---|---|
| LLM | **Provider-agnostic via LiteLLM** — Anthropic (default), OpenAI, Gemini, or local Ollama, chosen by one env var. All calls go through `llm.py`. |
| Orchestration | **LangGraph** stateful graph + **checkpointer + `interrupt()`** for true multi-turn HITL |
| Vector DB | **PostgreSQL 17 + pgvector** (raw psycopg) |
| ORM (memory/feedback) | **SQLAlchemy** models for `user_profiles` + `feedback` |
| Embeddings | Local, no API key — `fastembed` (BGE) **or** a no-download hashing fallback |
| Doc parsing | PyMuPDF (page-aware) + recursive character chunker; **manifest-driven** |
| Rule extraction | Claude extracts structured `reward_rules`/`transfer_partners` from PDFs w/ confidence + source-chunk citations |
| API / UI | FastAPI (`/ask`, `/resume`, `/feedback`, `/logs`, `/health`) + Streamlit |
| Monitoring | `recommendation_logs` + feedback + sidebar dashboard |
| Evaluation | retrieval (P@K/Recall@K/MRR), calculation, faithfulness, 22 golden cases |

## Setup (recreate anywhere)

```bash
brew install postgresql@17 pgvector && brew services start postgresql@17
createdb credit_rewards
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env      # then set ANTHROPIC_API_KEY
```

Edit `.env` — pick a provider with `LLM_MODEL` and set that provider's key:
```
LLM_MODEL=anthropic/claude-opus-4-8    # or openai/gpt-4o-mini, gemini/gemini-2.5-flash, ollama/llama3.1
ANTHROPIC_API_KEY=sk-ant-...           # set the key for whichever provider you chose
EMBED_BACKEND=hashing                  # no download; use "fastembed" off a restricted network
```

**Choose your LLM provider** (LiteLLM — one env var, no code changes):

| Provider | `LLM_MODEL` example | Key needed |
|---|---|---|
| Anthropic (default) | `anthropic/claude-opus-4-8` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai/gpt-4o-mini` | `OPENAI_API_KEY` |
| Google Gemini | `gemini/gemini-2.5-flash` | `GEMINI_API_KEY` |
| Local Ollama | `ollama/llama3.1` | none — fully offline (`ollama serve` + `ollama pull llama3.1`) |

Notes: embeddings are already local (provider-independent). The "add card by name → web search"
feature uses Anthropic's web-search tool, so it needs `LLM_MODEL=anthropic/...`; other providers
fall back to PDF upload or `rag/collect_web.py`. Extended thinking applies to Anthropic only.

## Card data — where it comes from

Card documents live in [`data/cards/`](data/cards/) and are the **source of truth**.
[`data/cards/manifest.csv`](data/cards/manifest.csv) maps each file *stem* → card name, issuer,
effective date, source URL.

- The `.md` files contain **real reward data compiled from public sources** (official bank pages +
  reputable aggregators), each with a provenance header (source URLs + retrieved date) and
  `(verify)` flags on anything uncertain. Reward terms drift — treat as illustrative and verify
  with the issuer. Data reflects mid-2026 (incl. recent devaluations).
- **Refresh from the web:** `python -m rag.collect_web` re-fetches the curated public URLs and has
  Claude recompile each doc (needs a key + web access; human-review the output).
- **Official PDFs:** if you obtain a bank's T&C PDF, save it as `data/cards/<stem>.pdf` using the
  stems in `manifest.csv` — a PDF **supersedes** the `.md` of the same stem automatically.
- Then extract structured rules with Claude: `python seed.py --extract` (below).

**Add a card at runtime — two front doors, one pipeline.** Both produce identical structured data
(`document_chunks` → `reward_rules` + `transfer_partners`):

```bash
python -m rag.add_card "ICICI Amazon Pay"              # by name -> Claude web-searches the terms
python -m rag.add_card "HDFC Regalia" --pdf terms.pdf  # from a PDF file
```
Also in the **Streamlit sidebar** ("➕ Add a card") and the **API**:
`POST /cards/add_web {card_name, issuer}` · `POST /cards/add_pdf` (multipart: `card_name`, `file`).
Both use Claude (web search + extraction), so they need `ANTHROPIC_API_KEY`.

## Run

```bash
# 1. Seed: schema + ingest docs + structured rules
.venv/bin/python seed.py                # hand-authored rules (offline, matches the .md docs)
.venv/bin/python seed.py --extract      # extract rules from ingested PDFs via Claude (needs key)

# 2. Ask
.venv/bin/python cli.py "I am spending Rs 50,000 on flights. Which card should I use?"
.venv/bin/python cli.py --user alice    # interactive, remembers profile across turns

# 3. UI / API
.venv/bin/streamlit run app/streamlit_app.py
.venv/bin/uvicorn backend.main:app --port 8000

# 4. Evaluate & test
.venv/bin/python evaluation/calculation_eval.py     # deterministic, no key
.venv/bin/python evaluation/rag_eval.py             # Precision@K / Recall@K / MRR, no key
.venv/bin/python evaluation/evaluate.py             # 22 golden cases (needs key)
.venv/bin/python evaluation/hallucination_eval.py   # faithfulness judge (needs key)
.venv/bin/python tests/test_calculator.py && .venv/bin/python tests/test_retrieval.py
```

## Capabilities mapped to the brief

- **Use Case 1** single transaction, **Use Case 2** monthly optimization (per-category allocation
  table), **Use Case 3** point transfer with human approval.
- **Memory:** `user_profiles` loaded at start (owned cards, preferred reward type, point
  valuation) and updated after each answer (incl. a conversation summary). Pass `--user`/`user_id`.
- **Human-in-the-loop:** LangGraph `interrupt()` + checkpointer — clarify/approval pause and
  resume on the same `thread_id` (real multi-turn), not a re-run.
- **Guardrails:** input (off-topic / prompt-injection → refusal) + output (grounding, caps,
  safe framing, disclaimer, effective date).
- **Monitoring:** every recommendation logged (latency, tokens, confidence, guardrail); feedback
  thumbs stored; sidebar dashboard.

## Project layout

```
config.py              config (LLM_MODEL provider routing) + truststore TLS injection
llm.py                 provider-agnostic LLM wrapper via LiteLLM (text + structured JSON + web search)
seed.py                schema + ingest + (synthetic | --extract) structured rules
cli.py                 CLI with multi-turn resume + feedback
database/  schema.sql, db.py (psycopg+pgvector), models.py (SQLAlchemy), seed_data.py
rag/       embeddings.py, ingest_pdfs.py (manifest, page-aware), extract_rules.py, collect_web.py, retrieval.py
tools/     calculator.py, retriever.py, rule_validator.py, transfer_calculator.py
agents/    state.py, prompts.py, nodes.py, graph.py (checkpointer + interrupt)
backend/   main.py (FastAPI)
app/       streamlit_app.py
monitoring/logger.py
evaluation/golden_answers.csv, retrieval_labels.csv, calculation_cases.csv,
           evaluate.py, rag_eval.py, calculation_eval.py, hallucination_eval.py
data/cards/manifest.csv + *.md (illustrative) [+ your *.pdf]
data/sample_queries.csv
```

## Notes

- **Card data is compiled from public web sources (cited), not official issuer documents**, and
  reward terms change frequently. The agent answers only from the documents and always appends a
  "verify with issuer / not financial advice" disclaimer.
- **Corporate network (Zscaler):** a TLS-inspecting proxy blocks model-download CDNs (Hugging Face,
  Google, **and the Ollama registry**) — so no model weights (embeddings or LLMs) can be pulled
  on-network. What still works: `truststore` (auto-injected in `config.py`) routes TLS through the
  macOS keychain so **cloud LLM APIs** (Anthropic/OpenAI/Gemini) are reachable; `EMBED_BACKEND=hashing`
  needs no download. For **local Ollama**, run `ollama pull llama3.2:3b` **once off-network**
  (hotspot/home); it then runs offline forever. If `pip install` tries to build a Rust wheel
  (e.g. a newer `tokenizers`), use `pip install --only-binary=:all: -r requirements.txt`.
- **Memory checkpointer** is in-process (`MemorySaver`) for the demo; swap for a Postgres
  checkpointer for a multi-process production deployment.
