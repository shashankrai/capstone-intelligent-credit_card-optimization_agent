# Installation & Local Setup Guide

**Intelligent Credit Card & Rewards Optimization Agent**

---

## Prerequisites

Before you start, make sure the following are installed on your machine.

| Requirement | Minimum Version | Check Command |
|---|---|---|
| Python | 3.11+ | `python3 --version` |
| PostgreSQL | 16+ | `psql --version` |
| pgvector extension | 0.7+ | (checked after DB setup) |
| Git | any | `git --version` |

> **macOS (recommended):** Install everything via Homebrew. Windows users can use WSL2.

---

## Step 1 — Install System Dependencies

### macOS

```bash
# Install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python 3.12
brew install python@3.12

# Install PostgreSQL 16
brew install postgresql@16

# Start PostgreSQL and set it to auto-start on login
brew services start postgresql@16

# Install pgvector extension
brew install pgvector
```

### Ubuntu / Debian (Linux / WSL2)

```bash
# Python
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-dev -y

# PostgreSQL 16
sudo apt install postgresql-16 postgresql-client-16 -y
sudo systemctl start postgresql
sudo systemctl enable postgresql

# pgvector
sudo apt install postgresql-16-pgvector -y
```

### Windows (Native — PowerShell)

> This is the fix for the `ConnectionTimeout: connection timeout expired` error on Windows.

**Option A — Docker Desktop (easiest, recommended for Windows)**

Docker gives you PostgreSQL + pgvector in one command, no manual extension setup needed.

1. Install [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)
2. Start Docker Desktop, then run:

```powershell
# Pull and start a postgres+pgvector container
docker run -d `
  --name cc-rewards-db `
  -e POSTGRES_DB=credit_rewards `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=postgres `
  -p 5432:5432 `
  pgvector/pgvector:pg16

# Verify it is running
docker ps
```

3. Set these values in your `.env`:
```
PGHOST=localhost
PGPORT=5432
PGDATABASE=credit_rewards
PGUSER=postgres
PGPASSWORD=postgres
```

4. Continue from **Step 4** (install Python packages).

---

**Option B — Native PostgreSQL installer on Windows**

1. Download the PostgreSQL 16 installer from [postgresql.org/download/windows](https://www.postgresql.org/download/windows/)
2. Run the installer — use the default port `5432`, set a password for the `postgres` user.
3. After install, open **Stack Builder** (launches automatically) → select your PostgreSQL 16 installation → expand **Add-ons, tools and utilities** → tick **pgvector** → Install.
4. Open **pgAdmin** or **SQL Shell (psql)** and run:

```sql
CREATE DATABASE credit_rewards;
\c credit_rewards
CREATE EXTENSION IF NOT EXISTS vector;
```

5. Set these in your `.env`:
```
PGHOST=localhost
PGPORT=5432
PGDATABASE=credit_rewards
PGUSER=postgres
PGPASSWORD=<the password you set during install>
```

---

**Python on Windows — use `python` not `python3`**

```powershell
# Create venv
python -m venv .venv

# Activate
.venv\Scripts\activate

# Install packages
pip install -r requirements.txt

# Run app
python -m streamlit run app/streamlit_app.py
```

---

### WSL2 (Ubuntu inside Windows)

Use the Ubuntu / Debian instructions above inside WSL2. This is the smoothest Windows experience — PostgreSQL behaves exactly like Linux.

---

## Step 2 — Get the Code

```bash
git clone <your-repo-url>
cd capstone-intelligent-credit_card-optimization_agent
```

---

## Step 3 — Create the Python Virtual Environment

```bash
# Create a fresh venv (always create from the project root)
python3 -m venv .venv

# Activate it
# macOS / Linux:
source .venv/bin/activate

# Windows (WSL2):
source .venv/bin/activate
```

You should see `(.venv)` in your terminal prompt after activation.

> **If you moved the project folder:** Virtual environments store absolute paths. If you moved or copied the project, delete the old `.venv` and recreate it with the commands above.

---

## Step 4 — Install Python Dependencies

```bash
# With venv activated:
pip install --upgrade pip
pip install -r requirements.txt
```

**On a corporate network (TLS-inspecting proxy):**

```bash
# If pip fails with SSL errors, use the --only-binary flag to skip Rust builds
pip install --only-binary=:all: -r requirements.txt
```

**What gets installed:**

| Package | Purpose |
|---|---|
| `litellm` | Provider-agnostic LLM calls (Anthropic / Gemini / OpenAI / Ollama) |
| `anthropic` | Native Anthropic client (for web-search tool) |
| `langgraph`, `langchain-core` | Agent graph orchestration |
| `fastembed` | Local ONNX embedding model (BAAI/bge-small-en-v1.5) |
| `psycopg[binary]`, `pgvector` | PostgreSQL + vector search |
| `SQLAlchemy` | ORM for user profiles and feedback |
| `pymupdf` | PDF text extraction |
| `fastapi`, `uvicorn` | REST API backend |
| `streamlit` | Web demo UI |
| `python-dotenv`, `pydantic` | Config + validation |
| `truststore` | OS trust store for TLS (corporate proxy support) |

---

## Step 5 — Set Up the PostgreSQL Database

### 5a. Create the database

```bash
# macOS (Homebrew) — your OS user is already a superuser, no password needed
createdb credit_rewards

# Linux — switch to the postgres user first
sudo -u postgres createdb credit_rewards
sudo -u postgres psql -c "CREATE USER $(whoami) WITH SUPERUSER;"
```

### 5b. Enable the pgvector extension

```bash
psql -d credit_rewards -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Verify it worked:

```bash
psql -d credit_rewards -c "SELECT extversion FROM pg_extension WHERE extname='vector';"
# Expected output:  0.7.x or higher
```

---

## Step 6 — Configure the .env File

Copy the example file and fill in your settings:

```bash
cp .env.example .env
```

Open `.env` in any editor and set the following:

```dotenv
# ── LLM Provider (pick ONE and set its key) ──────────────────────────────────

# Option A: Gemini (free tier — easiest to start with)
LLM_MODEL=gemini/gemini-2.5-flash
GEMINI_API_KEY=your_gemini_key_here
# Get a free Gemini key at: https://aistudio.google.com/apikey

# Option B: Anthropic / Claude
# LLM_MODEL=anthropic/claude-opus-4-8
# ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxx

# Option C: OpenAI
# LLM_MODEL=openai/gpt-4o-mini
# OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx

# Option D: Local Ollama (no key needed — fully offline)
# LLM_MODEL=ollama/llama3.1
# OLLAMA_API_BASE=http://localhost:11434

# ── PostgreSQL ────────────────────────────────────────────────────────────────
PGHOST=localhost
PGPORT=5432
PGDATABASE=credit_rewards
PGUSER=your_os_username       # run: whoami   to find this
PGPASSWORD=                   # leave blank for Homebrew / socket auth

# ── Embeddings (local, no API key needed) ─────────────────────────────────────
# auto = tries fastembed first, falls back to hashing
# hashing = works on corporate networks with no internet access
# fastembed = downloads ONNX model on first run (~90MB)
EMBED_BACKEND=auto
EMBED_MODEL=BAAI/bge-small-en-v1.5
EMBED_DIM=384
```

> **Tip — find your OS username:**
> ```bash
> whoami
> ```

---

## Step 7 — Run the Seed Pipeline

This creates the database schema, ingests all 5 card documents into pgvector, and populates the reward rules table.

```bash
# With venv activated:
python3 seed.py
```

Expected output:

```
[1/3] Initialising schema ...  done
[2/3] Ingesting card documents ...
  axis_atlas.md           → 12 chunks
  hdfc_diners_club_black.md → 14 chunks
  hdfc_infinia.md         → 11 chunks
  amex_platinum_travel.md → 13 chunks
  sbi_cashback.md         → 9 chunks
[3/3] Seeding structured reward rules ...  55 rules, 18 transfer partners
Setup complete.
```

Verify the data loaded:

```bash
psql -d credit_rewards -c "SELECT COUNT(*) FROM card_documents;"
# → 5

psql -d credit_rewards -c "SELECT COUNT(*) FROM reward_rules;"
# → 55

psql -d credit_rewards -c "SELECT COUNT(*) FROM document_chunks;"
# → 59 (approx)
```

> **Re-run seed at any time** to reset all data:
> ```bash
> python3 seed.py
> ```

> **LLM-powered rule extraction** (needs an API key, takes ~2–3 minutes):
> ```bash
> python3 seed.py --extract
> ```
> This uses the LLM to re-extract structured rules from the ingested document chunks. The default `seed.py` uses pre-authored fallback rules — good enough to start.

---

## Step 8 — Launch the App

### Option A: Streamlit Web UI (recommended for demo)

```bash
# With venv activated:
python3 -m streamlit run app/streamlit_app.py
```

Open your browser at: **http://localhost:8501**

The sidebar shows:
- Database: 🟢 connected
- Model: `gemini/gemini-2.5-flash`
- LLM ready: 🟢 yes

### Option B: Command-Line Interface

```bash
python3 cli.py
```

Interactive REPL — type any query and press Enter. Type `exit` to quit.

One-shot mode:

```bash
python3 cli.py -q "I am spending Rs 50000 on flights. I have Axis Atlas and HDFC DCB. Which card?"
```

### Option C: FastAPI REST Backend

```bash
python3 -m uvicorn backend.main:app --port 8000 --reload
```

API available at: **http://localhost:8000**
Interactive docs at: **http://localhost:8000/docs**

---

## Makefile Shortcuts

If you created the venv fresh from the project root (not moved), you can use:

```bash
make ui       # Streamlit UI at http://localhost:8501
make cli      # Interactive CLI
make api      # FastAPI at http://localhost:8000
make seed     # Reset and reseed the database
make test     # Run unit + integration tests
make eval     # Run all 4 evaluation scripts
```

> **Note:** `make` shortcuts use `.venv/bin/python` directly. If you moved the project folder, recreate the venv first (Step 3) so the paths are correct.

---

## Running Tests

```bash
# Unit tests — no database or API key required
python3 tests/test_calculator.py

# Integration tests — requires a seeded database (no API key required)
python3 tests/test_retrieval.py

# Both at once
python3 tests/test_calculator.py && python3 tests/test_retrieval.py
```

## Running Evaluations

```bash
# Retrieval quality (Precision@K, Recall@K, MRR)
python3 evaluation/rag_eval.py

# Calculator correctness (exact match)
python3 evaluation/calculation_eval.py

# Hallucination check (LLM-as-judge — needs API key)
python3 evaluation/hallucination_eval.py

# End-to-end golden answers (needs API key)
python3 evaluation/evaluate.py
```

---

## Adding a New Card

### From the Streamlit UI

Sidebar → "Add a card to the knowledge base" → choose **Search web by name** or **Upload PDF**.

### From the CLI / Python

```python
from rag.add_card import add_card_from_web, add_card_from_pdf

# Add by web search (needs LLM key + internet)
result = add_card_from_web("ICICI Amazon Pay", issuer="ICICI")
print(result)  # {'card_name': ..., 'chunks': ..., 'reward_rules': ...}

# Add from PDF bytes
with open("my_card.pdf", "rb") as f:
    result = add_card_from_pdf(f.read(), "My Card Name", issuer="My Bank")
```

---

## Switching the LLM Provider

Change one line in `.env` and restart the app — no code changes needed.

| Provider | LLM_MODEL value | Key variable | Cost |
|---|---|---|---|
| Gemini 2.5 Flash | `gemini/gemini-2.5-flash` | `GEMINI_API_KEY` | Free tier available |
| Claude Opus 4 | `anthropic/claude-opus-4-8` | `ANTHROPIC_API_KEY` | Paid |
| GPT-4o mini | `openai/gpt-4o-mini` | `OPENAI_API_KEY` | Paid |
| Llama 3.1 (local) | `ollama/llama3.1` | none | Free / fully offline |
| Gemini 2.0 Flash | `gemini/gemini-2.0-flash` | `GEMINI_API_KEY` | Free tier available |

---

## Troubleshooting

### `psql: error: connection refused`
PostgreSQL is not running. Start it:
```bash
# macOS
brew services start postgresql@16

# Linux
sudo systemctl start postgresql
```

### `extension "vector" does not exist`
pgvector is not installed or not enabled:
```bash
# macOS
brew install pgvector

# Then enable it in the database
psql -d credit_rewards -c "CREATE EXTENSION vector;"
```

### `LLM provider 'gemini' is not configured: GEMINI_API_KEY is not set`
Open `.env` and add your key:
```dotenv
GEMINI_API_KEY=your_key_here
```

### `streamlit: bad interpreter` or `uvicorn: command not found`
The venv was moved. Recreate it:
```bash
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### `SSL: CERTIFICATE_VERIFY_FAILED` (corporate network)
The project uses `truststore` to inject the OS certificate store. Make sure it installed:
```bash
pip install truststore
```
If the error persists, set:
```dotenv
# in .env
REQUESTS_CA_BUNDLE=/path/to/your/corporate-ca.pem
```

### `pip install` fails to build `tokenizers` from source
Use pre-built wheels:
```bash
pip install --only-binary=:all: -r requirements.txt
```

### Seed runs but `reward_rules` count is 0
Run the LLM extraction step (needs API key):
```bash
python3 seed.py --extract
```

---

## Environment Variables — Full Reference

| Variable | Default | Description |
|---|---|---|
| `LLM_MODEL` | `anthropic/claude-opus-4-8` | LiteLLM model string `provider/model` |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `OLLAMA_API_BASE` | `http://localhost:11434` | Ollama server URL |
| `CLAUDE_THINKING` | `false` | Enable extended thinking (Anthropic only) |
| `LLM_TIMEOUT` | `90` | LLM call timeout in seconds |
| `LLM_NUM_RETRIES` | `2` | Retry count on LLM failure |
| `PGHOST` | `localhost` | PostgreSQL host |
| `PGPORT` | `5432` | PostgreSQL port |
| `PGDATABASE` | `credit_rewards` | Database name |
| `PGUSER` | *(OS user)* | PostgreSQL user |
| `PGPASSWORD` | — | PostgreSQL password (blank = OS auth) |
| `EMBED_BACKEND` | `auto` | `auto` / `fastembed` / `hashing` |
| `EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | Embedding model name |
| `EMBED_DIM` | `384` | Embedding vector dimension |

---

## Sharing One PostgreSQL with the Team

If you want everyone to connect to **one central database** instead of each person running their own, follow these steps on the machine that hosts PostgreSQL (the Mac running the seeded DB).

### Step A — Allow remote connections on the host machine (macOS)

```bash
# Find the PostgreSQL config folder
psql -c "SHOW config_file;"
# Usually: /opt/homebrew/var/postgresql@16/postgresql.conf

# 1. Edit postgresql.conf — change listen address
#    Find:   listen_addresses = 'localhost'
#    Change: listen_addresses = '*'
nano /opt/homebrew/var/postgresql@16/postgresql.conf

# 2. Edit pg_hba.conf — allow password login from any IP
#    Add this line at the bottom:
#    host  credit_rewards  all  0.0.0.0/0  scram-sha-256
nano /opt/homebrew/var/postgresql@16/pg_hba.conf

# 3. Set a password for your DB user (required for remote auth)
psql -c "ALTER USER shashank.rai PASSWORD 'choose_a_password';"

# 4. Restart PostgreSQL to apply changes
brew services restart postgresql@16

# 5. Find your machine's local IP
ipconfig getifaddr en0
# Example output: 192.168.1.42
```

### Step B — Open the firewall port (macOS)

macOS does not block port 5432 by default. If you are on a corporate network, check that port 5432 is reachable between machines — test from a teammate's machine:

```powershell
# Windows PowerShell — test connectivity
Test-NetConnection -ComputerName 192.168.1.42 -Port 5432
# TcpTestSucceeded : True  means it is reachable
```

### Step C — Team members set `.env` to point at the host

Each team member adds these lines to their `.env` (replace the IP and password):

```dotenv
PGHOST=192.168.1.42        # IP of the machine running PostgreSQL
PGPORT=5432
PGDATABASE=credit_rewards
PGUSER=shashank.rai        # the DB user on the host
PGPASSWORD=choose_a_password
```

Team members **do NOT run** `seed.py` — the data is already on the host. They only need:
1. Python + venv + `pip install -r requirements.txt`
2. The `.env` file above
3. `python -m streamlit run app/streamlit_app.py` (or `python cli.py`)

### Option: Use Supabase free tier (cloud PostgreSQL with pgvector)

Supabase has pgvector built in and a generous free tier — good for demos accessible from anywhere.

1. Create a free project at [supabase.com](https://supabase.com)
2. In the Supabase dashboard → **Settings → Database** → copy the connection string
3. Set in `.env`:
```dotenv
PGHOST=db.<your-project-ref>.supabase.co
PGPORT=5432
PGDATABASE=postgres
PGUSER=postgres
PGPASSWORD=<supabase db password>
```
4. Run `python3 seed.py` once to create schema and seed data into Supabase.

---

## Quick-Start Checklist

```
[ ] Python 3.11+ installed
[ ] PostgreSQL 16+ installed and running
[ ] pgvector extension installed
[ ] git clone / unzip project
[ ] python3 -m venv .venv && source .venv/bin/activate
[ ] pip install -r requirements.txt
[ ] createdb credit_rewards
[ ] psql -d credit_rewards -c "CREATE EXTENSION vector;"
[ ] cp .env.example .env  →  fill in LLM key + PGUSER
[ ] python3 seed.py
[ ] python3 -m streamlit run app/streamlit_app.py
[ ] Open http://localhost:8501 — sidebar shows 🟢 connected + 🟢 LLM ready
```
