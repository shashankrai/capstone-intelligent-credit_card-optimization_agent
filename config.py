"""Central configuration. Loads from .env once and exposes typed settings."""
from __future__ import annotations

import getpass
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

# Use the OS trust store (macOS keychain) for TLS. This is what lets HTTPS work
# behind a corporate TLS-inspecting proxy whose root CA isn't in certifi's bundle
# (affects Anthropic API calls and any model downloads).
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

# ---- LLM provider (provider-agnostic via LiteLLM) ----
# LLM_MODEL is a LiteLLM model id: "<provider>/<model>", e.g.
#   anthropic/claude-opus-4-8 | openai/gpt-4o-mini | gemini/gemini-2.5-flash | ollama/llama3.1
# Back-compat: if LLM_MODEL is unset we fall back to anthropic/<CLAUDE_MODEL>.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-8").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "").strip() or f"anthropic/{CLAUDE_MODEL}"
if "/" not in LLM_MODEL:
    LLM_MODEL = f"anthropic/{LLM_MODEL}"
LLM_PROVIDER = LLM_MODEL.split("/", 1)[0]
CLAUDE_THINKING = os.getenv("CLAUDE_THINKING", "false").strip().lower() == "true"
# Fail-fast controls so a stuck/slow provider surfaces an error instead of hanging.
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))
LLM_NUM_RETRIES = int(os.getenv("LLM_NUM_RETRIES", "1"))

# Provider API keys (LiteLLM reads these from the environment; loaded here via .env).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
OLLAMA_API_BASE = os.getenv("OLLAMA_API_BASE", "http://localhost:11434").strip()

# Which env var holds the key for each provider (ollama needs none).
_PROVIDER_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                     "gemini": "GEMINI_API_KEY", "vertex_ai": "GEMINI_API_KEY"}


def llm_ready() -> bool:
    """True if the active provider has what it needs (a key, or nothing for ollama)."""
    if LLM_PROVIDER == "ollama":
        return True
    env = _PROVIDER_KEY_ENV.get(LLM_PROVIDER)
    return bool(os.getenv(env, "").strip()) if env else True

# ---- Embeddings ----
# EMBED_BACKEND: "auto" (try fastembed, fall back to local hashing), "fastembed", or "hashing".
# "hashing" needs no model download — use it on locked-down networks that block model CDNs.
EMBED_BACKEND = os.getenv("EMBED_BACKEND", "auto").strip().lower()
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5").strip()
EMBED_DIM = int(os.getenv("EMBED_DIM", "384"))

# ---- Database ----
PGHOST = os.getenv("PGHOST", "localhost").strip()
PGPORT = os.getenv("PGPORT", "5432").strip()
PGDATABASE = os.getenv("PGDATABASE", "credit_rewards").strip()
PGUSER = os.getenv("PGUSER", "").strip() or getpass.getuser()
PGPASSWORD = os.getenv("PGPASSWORD", "").strip()

# ---- Paths ----
CARDS_DIR = PROJECT_ROOT / "data" / "cards"

# ---- RAG ----
CHUNK_SIZE = 900          # characters per chunk (approx)
CHUNK_OVERLAP = 150
RETRIEVE_TOP_K = 6        # chunks returned by vector search


def db_dsn() -> str:
    """psycopg connection string. Empty password -> rely on socket/peer auth."""
    parts = [f"host={PGHOST}", f"port={PGPORT}", f"dbname={PGDATABASE}", f"user={PGUSER}"]
    if PGPASSWORD:
        parts.append(f"password={PGPASSWORD}")
    return " ".join(parts)


def require_api_key() -> None:
    """Ensure the active LLM provider is usable, else raise a clear message."""
    if llm_ready():
        return
    env = _PROVIDER_KEY_ENV.get(LLM_PROVIDER, "the provider API key")
    raise RuntimeError(
        f"LLM provider '{LLM_PROVIDER}' (model {LLM_MODEL}) is not configured: {env} is not set. "
        f"Add it to the .env file, or set LLM_MODEL to a provider you have access to "
        f"(e.g. ollama/llama3.1 for fully local)."
    )
