-- Intelligent Credit Card & Rewards Optimization Agent — database schema
-- Requires the pgvector extension. Embedding dimension is 384 (BAAI/bge-small-en-v1.5).

CREATE EXTENSION IF NOT EXISTS vector;

-- Table 1: card_documents — metadata about each ingested source document
CREATE TABLE IF NOT EXISTS card_documents (
    document_id   SERIAL PRIMARY KEY,
    card_name     TEXT NOT NULL,
    issuer        TEXT,
    document_type TEXT,
    effective_date DATE,
    source_url    TEXT,
    uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Table 2: document_chunks — RAG chunks + embeddings (unstructured store)
CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id      SERIAL PRIMARY KEY,
    document_id   INTEGER REFERENCES card_documents(document_id) ON DELETE CASCADE,
    card_name     TEXT NOT NULL,
    chunk_text    TEXT NOT NULL,
    page_number   INTEGER,
    embedding     vector(384),
    metadata_json JSONB DEFAULT '{}'::jsonb
);

-- Table 3: reward_rules — clean structured reward rules extracted from documents
CREATE TABLE IF NOT EXISTS reward_rules (
    rule_id          SERIAL PRIMARY KEY,
    card_name        TEXT NOT NULL,
    spend_category   TEXT NOT NULL,        -- flights, hotels, travel, dining, groceries, online, general, rent, fuel, ...
    reward_type      TEXT NOT NULL,        -- points | miles | cashback
    reward_rate      NUMERIC,              -- units earned
    reward_per_amount NUMERIC,             -- per how many rupees (e.g. 100, 150, 50)
    reward_unit      TEXT,                 -- EDGE Miles, Reward Points, MR Points, % cashback
    monthly_cap      NUMERIC,              -- cap on reward units per month (NULL = none)
    annual_cap       NUMERIC,
    point_value      NUMERIC,              -- assumed rupee value of 1 reward unit
    exclusion_flag   BOOLEAN DEFAULT FALSE,-- TRUE means the category earns nothing
    milestone_flag   BOOLEAN DEFAULT FALSE,
    notes            TEXT,
    source_document_id INTEGER REFERENCES card_documents(document_id) ON DELETE SET NULL,
    source_chunk_id  INTEGER REFERENCES document_chunks(chunk_id) ON DELETE SET NULL,
    confidence_score NUMERIC DEFAULT 0.8
);

-- Table 4: transfer_partners — point/mile transfer rules
CREATE TABLE IF NOT EXISTS transfer_partners (
    partner_id      SERIAL PRIMARY KEY,
    card_name       TEXT NOT NULL,
    partner_name    TEXT NOT NULL,
    partner_type    TEXT,                 -- airline | hotel
    transfer_ratio  NUMERIC,              -- card units required per 1 partner unit (e.g. 2 means 2:1)
    minimum_points  NUMERIC,
    maximum_points  NUMERIC,
    effective_date  DATE,
    source_document_id INTEGER REFERENCES card_documents(document_id) ON DELETE SET NULL,
    source_chunk_id INTEGER REFERENCES document_chunks(chunk_id) ON DELETE SET NULL
);

-- Table 5: user_profiles — preferences / memory / personalization
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id              TEXT PRIMARY KEY,
    cards_owned          JSONB DEFAULT '[]'::jsonb,
    preferred_reward_type TEXT,
    point_valuation      NUMERIC,
    monthly_spend_pattern JSONB DEFAULT '{}'::jsonb,
    preferred_partners   JSONB DEFAULT '[]'::jsonb,
    conversation_summary TEXT,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Table 6: recommendation_logs — monitoring / observability
CREATE TABLE IF NOT EXISTS recommendation_logs (
    query_id         SERIAL PRIMARY KEY,
    user_id          TEXT,
    query_text       TEXT,
    intent           TEXT,
    retrieved_chunks JSONB,
    recommended_card TEXT,
    estimated_value  NUMERIC,
    confidence       TEXT,
    guardrail_passed BOOLEAN,
    latency_ms       INTEGER,
    input_tokens     INTEGER,
    output_tokens    INTEGER,
    final_answer     TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Table 7: feedback — user thumbs up/down + notes on a recommendation (Stage 3)
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id  SERIAL PRIMARY KEY,
    query_id     INTEGER REFERENCES recommendation_logs(query_id) ON DELETE CASCADE,
    user_id      TEXT,
    rating       TEXT,                 -- 'up' | 'down'
    note         TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Vector similarity index (cosine). ivfflat needs data first; created in seed step.
