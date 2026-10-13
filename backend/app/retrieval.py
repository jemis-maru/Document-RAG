"""
Question -> the few passages that answer it.

  1. scope     Does the question name a part of the document ("Chapter 3",
               "South Asia", "executive summary")? Then search only there.
               This is what stops a long report from mixing up regions.
  2. hybrid    Two searches, both inside Postgres:
                 vector  -- meaning ("power draw" finds "energy consumption")
                 keyword -- exact terms ("FDsys", "ENERGY STAR", "802,834")
               Each catches what the other misses on numbers and names.
  3. fuse      Reciprocal Rank Fusion: combine the two ranked lists by rank,
               not by their incomparable raw scores.
  4. rerank    A cross-encoder reads (question, passage) together and scores
               how well the passage ANSWERS the question. Slower than vectors,
               so it only sees the ~30 fused candidates.
  5. floor     Passages below MIN_RERANK_SCORE are dropped. An off-topic
               question gets nothing, so the model says "not in the document"
               instead of improvising from loosely related text.
  6. expand    The best text hits are joined with the chunk before/after them
               in the same section, so an answer split across a chunk
               boundary arrives whole.
"""

import re
import time

from . import config, db, models

STOPWORDS = set(
    "a an and are as at be by does did do for from has have how in is it its of on or "
    "say says said the this that to was were what when where which who why will with about "
    "according report document tell me give main".split()
)


def _norm(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", text.lower()).strip() + " "


_titles_cache: dict[int, list[str]] = {}


def _section_titles(doc_id: int) -> list[str]:
    if doc_id not in _titles_cache:
        rows = db.fetch_all(
            "SELECT DISTINCT unnest(section_path) AS t FROM chunks WHERE document_id=%s", (doc_id,)
        )
        _titles_cache[doc_id] = [r["t"] for r in rows]
    return _titles_cache[doc_id]


def detect_scope(doc_id: int, question: str) -> list[str]:
    """Section titles the question explicitly names. Only distinctive titles
    count (2+ meaningful words, or 'Chapter N'), so 'Outlook' or 'Risks' on
    their own never narrow the search."""
    q = _norm(question)
    matched = []
    for title in _section_titles(doc_id):
        m = re.match(r"chapter (\d+)", title.lower())
        if m and re.search(rf"\b(chapter|ch\.?)\s*{m.group(1)}\b", question.lower()):
            matched.append(title)
            continue
        words = [w for w in _norm(title).split() if w not in STOPWORDS]
        if len(words) >= 2 and _norm(title) in q:
            matched.append(title)
    # Drop titles contained in a longer matched title.
    return [t for t in matched if not any(t != o and _norm(t) in _norm(o) for o in matched)]


def _hybrid(doc_id: int, question: str, qvec, scope: list[str] | None) -> list[dict]:
    scope_sql = "AND section_path @> %(scope)s" if scope else ""
    params = {"doc": doc_id, "vec": qvec, "q": question, "scope": scope, "n": config.CANDIDATES}
    vector_rows = db.fetch_all(
        f"""SELECT id, 1 - (embedding <=> %(vec)s::vector) AS sim FROM chunks
             WHERE document_id = %(doc)s {scope_sql}
             ORDER BY embedding <=> %(vec)s::vector LIMIT %(n)s""",
        params,
    )
    # OR together the question's stemmed words: plainto_tsquery would AND
    # them, and a 12-word question would then match nothing.
    keyword_rows = db.fetch_all(
        f"""WITH q AS (
              SELECT to_tsquery('simple', string_agg(lexeme, ' | ')) AS q
                FROM unnest(to_tsvector('english', %(q)s)))
            SELECT id, ts_rank_cd(tsv, q.q) AS rank FROM chunks, q
             WHERE document_id = %(doc)s {scope_sql} AND q.q IS NOT NULL AND tsv @@ q.q
             ORDER BY rank DESC LIMIT %(n)s""",
        params,
    )
    fused: dict[int, dict] = {}
    for method, rows in (("vector", vector_rows), ("keyword", keyword_rows)):
        for rank, r in enumerate(rows):
            f = fused.setdefault(r["id"], {"id": r["id"], "rrf": 0.0, "vector_rank": None, "keyword_rank": None})
            f["rrf"] += 1 / (60 + rank)  # 60 is the standard RRF damping constant
            f[f"{method}_rank"] = rank + 1
    top = sorted(fused.values(), key=lambda f: -f["rrf"])[: config.CANDIDATES]
    if not top:
        return []
    rows = db.fetch_all(
        "SELECT id, seq, kind, section_path, section_id, page_start, page_end, content FROM chunks WHERE id = ANY(%s)",
        ([f["id"] for f in top],),
    )
    by_id = {r["id"]: r for r in rows}
    return [{**by_id[f["id"]], **f} for f in top if f["id"] in by_id]


def _passage_text(c: dict) -> str:
    return (" > ".join(c["section_path"][-3:]) + "\n" + c["content"])[:2000]


def _rank(doc_id: int, question: str, qvec, scope: list[str] | None):
    candidates = _hybrid(doc_id, question, qvec, scope)
    scores = models.rerank(question, [_passage_text(c) for c in candidates])
    for c, s in zip(candidates, scores):
        c["score"] = s
    candidates.sort(key=lambda c: -c["score"])
    hits = [c for c in candidates if c["score"] >= config.MIN_RERANK_SCORE][: config.RETRIEVE_K]
    return candidates, hits


def retrieve(doc_id: int, question: str) -> dict:
    t0 = time.time()
    qvec = models.embed_query(question)

    scope = detect_scope(doc_id, question) if config.ENABLE_SECTION_SCOPE else []
    candidates, hits = [], []
    if scope:
        candidates, hits = _rank(doc_id, question, qvec, scope)
        if not hits and len(scope) > 1:  # e.g. two named titles never share a path
            scope = scope[:1]
            candidates, hits = _rank(doc_id, question, qvec, scope)
    if not hits:
        # No scope named -- or the scope was a wrong guess from the wording and
        # held nothing relevant: search the whole document before giving up.
        scope = []
        candidates, hits = _rank(doc_id, question, qvec, None)

    passages = _expand(doc_id, hits) if config.ENABLE_NEIGHBORS else [_as_passage([h], h) for h in hits]
    return {
        "scope": scope,
        "passages": passages,
        "candidates": [_debug_row(c) for c in candidates[:15]],
        "retrieval_ms": int((time.time() - t0) * 1000),
    }


def _expand(doc_id: int, hits: list[dict]) -> list[dict]:
    """Join the top text hits with their neighbours in the same section, within
    the MAX_CONTEXT_CHARS budget. Tables and chart descriptions are already
    self-contained and are not expanded."""
    budget = config.MAX_CONTEXT_CHARS - sum(len(h["content"]) for h in hits)
    used = {h["id"] for h in hits}
    passages = []
    for rank, h in enumerate(hits):
        group = [h]
        if rank < 3 and h["kind"] == "text" and budget > 0:
            rows = db.fetch_all(
                "SELECT id, seq, kind, section_path, section_id, page_start, page_end, content FROM chunks "
                "WHERE document_id=%s AND section_id=%s AND kind='text' AND seq IN (%s, %s)",
                (doc_id, h["section_id"], h["seq"] - 1, h["seq"] + 1),
            )
            for r in rows:
                if r["id"] not in used and len(r["content"]) <= budget:
                    group.append(r)
                    used.add(r["id"])
                    budget -= len(r["content"])
        passages.append(_as_passage(sorted(group, key=lambda c: c["seq"]), h))
    return passages


def _as_passage(group: list[dict], hit: dict) -> dict:
    text = group[0]["content"]
    for nxt in group[1:]:
        # Consecutive chunks overlap by a sentence or two -- don't repeat it.
        first, _, rest = nxt["content"].partition("\n")
        text += "\n" + (rest if rest and text.rstrip().endswith(first.strip()) else nxt["content"])
    return {
        "chunk_id": hit["id"],
        "kind": hit["kind"],
        "section": " > ".join(hit["section_path"]),
        "page_start": min(c["page_start"] for c in group),
        "page_end": max(c["page_end"] for c in group),
        "score": round(hit["score"], 3),
        "vector_rank": hit.get("vector_rank"),
        "keyword_rank": hit.get("keyword_rank"),
        "expanded": len(group) > 1,
        "text": text,
    }


def _debug_row(c: dict) -> dict:
    return {
        "chunk_id": c["id"],
        "kind": c["kind"],
        "section": " > ".join(c["section_path"][-3:]),
        "page": c["page_start"],
        "score": round(c["score"], 3),
        "vector_rank": c["vector_rank"],
        "keyword_rank": c["keyword_rank"],
        "preview": c["content"][:140],
    }
