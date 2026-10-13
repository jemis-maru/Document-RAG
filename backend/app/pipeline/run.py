"""
The ingest pipeline, stage by stage, with live progress written to the
documents row so the UI can show what is happening:

  parse   PDF -> headings, paragraphs, tables, figures, footnotes   (parse.py)
  detect  what kind of document is this? (no AI -- layout statistics)
  vision  chart pages -> text with Gemini, cached                   (vision.py)
  chunk   section-aware chunks, footnotes attached                   (chunk.py)
  embed   local embedding model, no quota
  store   chunks + vectors + full-text index into Postgres
"""

import threading
import time
import traceback
from collections import Counter

from psycopg.types.json import Jsonb

from .. import config, db, models
from .chunk import build_chunks
from .parse import parse_pdf
from .vision import describe_pages, pick_visual_pages

STAGES = ["parse", "detect", "vision", "chunk", "embed", "store"]

# One document at a time: embedding is CPU-bound, and two parallel ingests
# would just each take twice as long.
_ingest_lock = threading.Lock()


class Progress:
    def __init__(self, doc_id: int):
        self.doc_id = doc_id
        self.state = {s: {"status": "pending"} for s in STAGES}
        self._t = 0.0

    def _save(self, stage: str | None):
        db.execute(
            "UPDATE documents SET stage=%s, progress=%s, updated_at=now() WHERE id=%s",
            (stage, Jsonb(self.state), self.doc_id),
        )

    def start(self, stage: str, detail: str = ""):
        self._t = time.time()
        self.state[stage] = {"status": "running", "detail": detail}
        self._save(stage)

    def update(self, stage: str, detail: str):
        self.state[stage]["detail"] = detail
        self._save(stage)

    def done(self, stage: str, detail: str = "", status: str = "done"):
        self.state[stage] = {"status": status, "detail": detail, "ms": int((time.time() - self._t) * 1000)}
        self._save(stage)


def run_pipeline(doc_id: int, path: str, sha: str) -> None:
    with _ingest_lock:
        prog = Progress(doc_id)
        try:
            _run(doc_id, path, sha, prog)
        except Exception as e:  # surface ANY failure in the UI instead of hanging
            traceback.print_exc()
            db.execute(
                "UPDATE documents SET status='failed', error=%s, updated_at=now() WHERE id=%s",
                (f"{type(e).__name__}: {e}", doc_id),
            )


def _run(doc_id: int, path: str, sha: str, prog: Progress) -> None:
    prog.start("parse")
    parsed = parse_pdf(path)
    s = parsed.stats
    prog.done(
        "parse",
        f"{parsed.pages} pages, {s.get('headings', 0)} headings, {s.get('tables', 0)} tables, "
        f"{s.get('figures', 0)} figures, {s.get('notes', 0)} footnotes",
    )

    prog.start("detect")
    visual_pages = pick_visual_pages(parsed.page_stats, parsed.pages)
    profile = _profile(parsed, visual_pages)
    prog.done("detect", profile["shape"])

    prog.start("vision")
    if visual_pages:
        visual, vinfo = describe_pages(
            path, sha, visual_pages, on_progress=lambda d, t: prog.update("vision", f"{d}/{t} pages")
        )
        detail = f"{len(visual)} chart pages described ({vinfo['called']} Gemini calls, {vinfo['cached']} from cache)"
        if vinfo["failed"]:
            detail += f", {len(vinfo['failed'])} failed: {vinfo['failed'][0]['error']}"
        profile["vision"] = vinfo
        prog.done("vision", detail, "done" if not vinfo["failed"] else "warning")
    else:
        visual = {}
        why = (
            f"skipped: {parsed.pages} pages is above the {config.VISION_DOC_MAX_PAGES}-page vision limit "
            "(figures are indexed from captions and notes)"
            if parsed.pages > config.VISION_DOC_MAX_PAGES
            else "skipped: no chart-heavy pages"
        )
        prog.done("vision", why, "skipped")

    prog.start("chunk")
    chunks = build_chunks(parsed, visual)
    kinds = Counter(c.kind for c in chunks)
    profile["chunks"] = dict(kinds)
    profile["sections"] = len({c.section_id for c in chunks})
    profile["footnotes_attached"] = sum(1 for c in chunks if "Footnotes cited above" in c.content)
    prog.done("chunk", f"{len(chunks)} chunks (" + ", ".join(f"{v} {k}" for k, v in kinds.most_common()) + ")")

    title = parsed.title or db.fetch_one("SELECT filename FROM documents WHERE id=%s", (doc_id,))["filename"]
    prog.start("embed", f"0/{len(chunks)}")
    vectors = models.embed_documents(
        [c.embed_text(title) for c in chunks],
        on_progress=lambda d, t: prog.update("embed", f"{d}/{t} chunks") if d % 128 == 0 or d == t else None,
    )
    prog.done("embed", f"{len(vectors)} vectors, {len(vectors[0]) if vectors else 0} dimensions (local model)")

    prog.start("store")
    with db.pool.connection() as conn, conn.transaction():
        conn.execute("DELETE FROM chunks WHERE document_id=%s", (doc_id,))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (document_id, seq, kind, section_path, section_text, section_id, page_start, "
                "page_end, content, embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [
                    (doc_id, c.seq, c.kind, c.section_path, " > ".join(c.section_path), c.section_id,
                     c.page_start, c.page_end, c.content, v)
                    for c, v in zip(chunks, vectors)
                ],
            )
        conn.execute(
            "UPDATE documents SET status='ready', title=%s, pages=%s, profile=%s, updated_at=now() WHERE id=%s",
            (title, parsed.pages, Jsonb(profile), doc_id),
        )
    prog.done("store", f"{len(chunks)} chunks saved with vector + keyword indexes")


def _profile(parsed, visual_pages: list[int]) -> dict:
    """What the parser found, in plain words -- shown to the user after upload.
    No AI involved: these are layout statistics."""
    s = parsed.stats
    pages = parsed.pages
    chars = sum(p["chars"] for p in parsed.page_stats)
    graphic_pages = sum(1 for p in parsed.page_stats if p["drawings"] >= 25 or p["image_ratio"] >= 0.15)

    if pages <= config.VISION_DOC_MAX_PAGES and graphic_pages / max(pages, 1) >= 0.4:
        shape = "Visual — facts live in charts, tables and call-outs"
    elif pages >= 120:
        shape = "Long & structured — chapters, sections and sub-sections"
    else:
        shape = "Narrative — mostly running text"

    strategies = []
    if s.get("headings"):
        strategies.append(
            f"Section-aware chunking: {s['headings']} headings over {s.get('heading_levels', 1)} levels; "
            "every chunk carries its section path"
        )
    if s.get("tables"):
        strategies.append(f"{s['tables']} tables rebuilt row by row, kept whole with their caption and notes")
    if s.get("figures"):
        strategies.append(f"{s['figures']} figures indexed from their captions, notes and panel titles")
    if visual_pages:
        strategies.append(f"{len(visual_pages)} chart-heavy pages sent to Gemini vision: {visual_pages}")
    if s.get("notes"):
        strategies.append(f"{s['notes']} footnotes found and attached to the passages that cite them")
    strategies.append("Running headers, footers and page numbers removed")

    return {
        "shape": shape,
        "pages": pages,
        "chars_per_page": chars // max(pages, 1),
        "graphic_pages": graphic_pages,
        "visual_pages": visual_pages,
        "stats": s,
        "strategies": strategies,
    }
