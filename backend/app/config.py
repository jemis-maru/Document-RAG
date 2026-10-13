"""
Every tunable knob in one place, read from backend/.env.

Change a value, restart the backend, and see what it does to the answers --
that is most of the learning in this project.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


def _int(name: str, default: int) -> int:
    return int(os.getenv(name) or default)


def _float(name: str, default: float) -> float:
    return float(os.getenv(name) or default)


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None or raw == "" else raw.strip().lower() in ("1", "true", "yes")


# --- services ---------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CHAT_MODEL = os.getenv("CHAT_MODEL", "gemini-3.6-flash")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://bacancy:devpass@localhost:5432/docrag")
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "http://localhost:3200")
UPLOAD_DIR = BACKEND_DIR / "uploads"

# --- local models (downloaded from Hugging Face on first use, then cached) ---
# bge-small: 384-dim, ~130 MB, fast on CPU, and strong for its size on retrieval
# benchmarks. The cross-encoder reranker reads (question, chunk) pairs together,
# which is slower than comparing vectors but far better at "does this chunk
# actually answer the question".
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_DIMS = _int("EMBED_DIMS", 384)
RERANK_MODEL = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

# --- upload limits (they protect the free Gemini quota) ---------------------
MAX_PAGES = _int("MAX_PAGES", 250)
MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 40)

# --- parsing -----------------------------------------------------------------
# Chart pages are sent to Gemini vision once (then cached). Only for short
# documents: in a short visual report the charts ARE the content, while a long
# report's figures are backed by captions, notes and the surrounding text.
ENABLE_VISION = _bool("ENABLE_VISION", True)
VISION_DOC_MAX_PAGES = _int("VISION_DOC_MAX_PAGES", 40)
VISION_MAX_PAGES = _int("VISION_MAX_PAGES", 15)

# --- chunking ----------------------------------------------------------------
CHUNK_CHARS = _int("CHUNK_CHARS", 1200)
CHUNK_OVERLAP = _int("CHUNK_OVERLAP", 200)

# --- retrieval ---------------------------------------------------------------
CANDIDATES = _int("CANDIDATES", 30)  # per search method, before reranking
RETRIEVE_K = _int("RETRIEVE_K", 6)  # chunks that reach the prompt
# Reranker scores are logits: > 0 means "likely relevant". Below the floor a
# chunk is dropped, so an off-topic question gets an honest "not in the
# document" instead of six loosely related paragraphs.
MIN_RERANK_SCORE = _float("MIN_RERANK_SCORE", -4.0)
ENABLE_SECTION_SCOPE = _bool("ENABLE_SECTION_SCOPE", True)
ENABLE_NEIGHBORS = _bool("ENABLE_NEIGHBORS", True)
MAX_CONTEXT_CHARS = _int("MAX_CONTEXT_CHARS", 12000)
ENABLE_QUERY_REWRITE = _bool("ENABLE_QUERY_REWRITE", True)
