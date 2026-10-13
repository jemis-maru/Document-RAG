"""
Postgres connection pool and schema.

Three tables:
  documents     one row per uploaded PDF (keyed by its SHA-256, so the same file
                uploaded twice is processed once), with live pipeline progress
  chunks        the searchable pieces: text, a pgvector embedding, and a
                full-text tsvector -- so vector AND keyword search run here
  vision_cache  Gemini's description of each chart page, so re-processing a
                document never spends the free quota twice
"""

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector

from . import config

pool: ConnectionPool | None = None


def _configure(conn):
    register_vector(conn)


def init_db() -> None:
    global pool
    # The extension must exist before register_vector can find the type, so
    # check it on a plain connection first and fail with a readable message.
    import psycopg

    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        try:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except psycopg.errors.InsufficientPrivilege as e:
            raise RuntimeError(
                "The pgvector extension is not installed in this database. Run:\n"
                "  sudo -u postgres psql -d docrag -c 'CREATE EXTENSION vector;'"
            ) from e

    pool = ConnectionPool(
        config.DATABASE_URL,
        min_size=1,
        max_size=5,
        configure=_configure,
        kwargs={"row_factory": dict_row, "autocommit": True},
        open=True,
    )
    with pool.connection() as conn:
        conn.execute(SCHEMA.format(dims=config.EMBED_DIMS))


SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id          SERIAL PRIMARY KEY,
  sha256      TEXT UNIQUE NOT NULL,
  filename    TEXT NOT NULL,
  title       TEXT,
  pages       INT,
  status      TEXT NOT NULL DEFAULT 'processing',   -- processing | ready | failed
  stage       TEXT,                                  -- current pipeline stage
  progress    JSONB NOT NULL DEFAULT '{{}}',          -- per-stage status + timings
  profile     JSONB,                                 -- what the parser detected
  error       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
  id            BIGSERIAL PRIMARY KEY,
  document_id   INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  seq           INT NOT NULL,                 -- reading order, used for neighbours
  kind          TEXT NOT NULL,                -- text | table | figure | visual | notes
  section_path  TEXT[] NOT NULL DEFAULT '{{}}',
  section_text  TEXT NOT NULL DEFAULT '',      -- the same path as one string, for the index
  section_id    INT NOT NULL DEFAULT 0,       -- chunks of one section share this
  page_start    INT NOT NULL,
  page_end      INT NOT NULL,
  content       TEXT NOT NULL,                -- what the LLM and the UI see
  embedding     vector({dims}),
  -- Section titles are weighted A so "South Asia" in a question favours chunks
  -- that live UNDER the South Asia heading, not ones that merely mention it.
  tsv           TSVECTOR GENERATED ALWAYS AS (
                  setweight(to_tsvector('english', section_text), 'A') ||
                  setweight(to_tsvector('english', content), 'B')
                ) STORED
);
CREATE INDEX IF NOT EXISTS chunks_doc_seq ON chunks (document_id, seq);
CREATE INDEX IF NOT EXISTS chunks_tsv ON chunks USING GIN (tsv);

CREATE TABLE IF NOT EXISTS vision_cache (
  sha256      TEXT NOT NULL,
  page        INT NOT NULL,
  model       TEXT NOT NULL,
  description TEXT NOT NULL,
  PRIMARY KEY (sha256, page, model)
);
"""


def fetch_all(sql: str, params=()) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def fetch_one(sql: str, params=()) -> dict | None:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql: str, params=()) -> None:
    with pool.connection() as conn:
        conn.execute(sql, params)
