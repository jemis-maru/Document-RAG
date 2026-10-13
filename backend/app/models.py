"""
The two local models. Both are loaded lazily (first use downloads them from
Hugging Face into ~/.cache/huggingface, after that it is offline) and kept in
memory for the life of the process.

  embedder  text -> 384 numbers. Similar meaning -> nearby vectors.
  reranker  (question, chunk) -> one relevance score. Reads both texts
            together, so it catches what vector similarity misses: a chunk
            that shares the topic but does not contain the answer.
"""

import threading

from . import config

# bge models were trained with this instruction on the QUERY side only.
# Leaving it off measurably hurts retrieval; adding it to documents hurts too.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

_lock = threading.Lock()
_embedder = None
_reranker = None


def embedder():
    global _embedder
    with _lock:
        if _embedder is None:
            from sentence_transformers import SentenceTransformer

            _embedder = SentenceTransformer(config.EMBED_MODEL, device="cpu")
    return _embedder


def reranker():
    global _reranker
    with _lock:
        if _reranker is None:
            from sentence_transformers import CrossEncoder

            _reranker = CrossEncoder(config.RERANK_MODEL, device="cpu", max_length=512)
    return _reranker


def embed_documents(texts: list[str], on_progress=None, batch: int = 32) -> list[list[float]]:
    model = embedder()
    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        vecs = model.encode(texts[i : i + batch], normalize_embeddings=True)
        out.extend(v.tolist() for v in vecs)
        if on_progress:
            on_progress(min(i + batch, len(texts)), len(texts))
    return out


def embed_query(text: str) -> list[float]:
    return embedder().encode(QUERY_INSTRUCTION + text, normalize_embeddings=True).tolist()


def rerank(query: str, passages: list[str]) -> list[float]:
    if not passages:
        return []
    return [float(s) for s in reranker().predict([(query, p) for p in passages])]
