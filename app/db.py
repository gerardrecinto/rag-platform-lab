import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from . import config

SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS chunks (
  id BIGSERIAL PRIMARY KEY, source TEXT NOT NULL, ord INT NOT NULL, text TEXT NOT NULL,
  embedding vector({config.EMBED_DIM}) NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, status TEXT NOT NULL, chunks INT DEFAULT 0, redactions INT DEFAULT 0,
  error TEXT, updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS llm_calls (
  id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT now(), provider TEXT, model TEXT,
  prompt_tokens INT, completion_tokens INT, tokens_estimated BOOLEAN, latency_ms INT,
  retrieved INT, query_hash TEXT);
"""

_pool = None


def _configure(conn):
    register_vector(conn)


def pool():
    global _pool
    if _pool is None:
        _pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=5, configure=_configure, open=True)
    return _pool


def init_schema():
    # The extension must exist before the pool registers the vector type.
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as c:
        c.execute(SCHEMA)
