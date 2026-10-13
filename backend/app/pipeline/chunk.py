"""
Elements -> chunks.

The rules, and why:

  * A chunk never crosses a heading. Each chunk carries its SECTION PATH
    ("Regional Outlooks > South Asia > Outlook"), which is embedded with it and
    weighted heavily in keyword search. That is what lets a long report tell
    two regions' near-identical growth paragraphs apart.
  * Narrative text is packed into ~CHUNK_CHARS chunks on sentence boundaries,
    with a small overlap so a fact split across two chunks is whole in one.
  * Tables, figures and chart descriptions are their OWN chunks and are never
    cut in the middle of a row. A long table is split by rows with its caption
    and header repeated, so every piece still says what its numbers mean.
  * Footnotes cited in a chunk are appended to it. The claim and the caveat
    that limits it travel together into the prompt.
"""

import re
from dataclasses import dataclass, field

from .. import config
from .parse import Element, ParsedDoc


@dataclass
class Chunk:
    seq: int
    kind: str
    section_path: list
    section_id: int
    page_start: int
    page_end: int
    content: str
    refs: list = field(default_factory=list)

    def embed_text(self, title: str) -> str:
        # The section path goes INTO the embedded text: a paragraph that never
        # says "South Asia" still lands near a South Asia question.
        path = " > ".join(self.section_path[-3:])
        head = f"{title}\nSection: {path}\n" if path else f"{title}\n"
        return (head + self.content)[:2000]


SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])")


def _sentences(text: str) -> list[str]:
    return [s for s in SENTENCE_RE.split(text) if s.strip()]


def _tail(text: str, n: int) -> str:
    """The last ~n characters, starting at a sentence boundary."""
    if len(text) <= n:
        return text
    sents = _sentences(text)
    out = ""
    for s in reversed(sents):
        if len(out) + len(s) > n and out:
            break
        out = f"{s} {out}".strip()
    return out


def build_chunks(doc: ParsedDoc, visual: dict[int, str]) -> list[Chunk]:
    """visual: page number -> Gemini's description of that page's charts."""
    target, overlap = config.CHUNK_CHARS, config.CHUNK_OVERLAP
    chunks: list[Chunk] = []
    stack: list[tuple[int, str]] = []  # (level, title)
    section_id = 0
    buf, buf_pages, buf_refs = "", [], []
    carried = ""  # overlap text carried into the next chunk

    def path():
        return [t for _, t in stack]

    def emit(kind, content, pages, refs=()):
        chunks.append(
            Chunk(len(chunks), kind, path(), section_id, min(pages), max(pages), content.strip(), list(dict.fromkeys(refs)))
        )

    def flush_text():
        nonlocal buf, buf_pages, buf_refs, carried
        if buf.strip() and buf.strip() != carried.strip():
            emit("text", buf, buf_pages, buf_refs)
            carried = _tail(buf, overlap)
        buf, buf_pages, buf_refs = "", [], []

    def add_text(text, page, refs):
        nonlocal buf, buf_pages, buf_refs
        # Short paragraphs go in whole; an oversized one is split into sentences.
        pieces = _sentences(text) if len(text) > target else [text]
        for i, piece in enumerate(pieces):
            if buf and len(buf) + len(piece) > target:
                flush_text()
                buf, buf_pages = carried, [page]
            sep = " " if i > 0 else "\n"  # sentences of one paragraph stay on one line
            buf = f"{buf}{sep}{piece}" if buf else piece
            buf_pages.append(page)
        buf_refs += refs

    visual_left = dict(visual)
    for el in doc.elements:
        # A page's chart description goes in right before the page's content.
        for p in sorted(visual_left):
            if p <= el.page:
                flush_text()
                emit("visual", f"[Charts and visuals on page {p}, described]\n{visual_left.pop(p)}", [p])

        if el.kind == "heading":
            flush_text()
            carried = ""  # never carry text across a section boundary
            while stack and stack[-1][0] >= el.level:
                stack.pop()
            stack.append((el.level, el.text))
            section_id += 1
        elif el.kind in ("text", "note"):
            add_text(el.text, el.page, el.refs)
        else:  # table | figure
            flush_text()
            for piece in _split_block(el.text, target + 600):
                emit(el.kind, piece, [el.page], el.refs)
    flush_text()
    for p, desc in sorted(visual_left.items()):
        emit("visual", f"[Charts and visuals on page {p}, described]\n{desc}", [p])

    # Attach cited footnotes.
    for c in chunks:
        cited = [n for n in c.refs if n in doc.notes]
        if cited:
            c.content += "\n\nFootnotes cited above:\n" + "\n".join(f"[{n}] {doc.notes[n]}" for n in cited)
    return [c for c in chunks if len(c.content) > 30]


def _split_block(text: str, limit: int) -> list[str]:
    """Split a table by rows, repeating the caption and header row on each piece."""
    if len(text) <= limit:
        return [text]
    lines = text.split("\n")
    header = "\n".join(lines[:2])
    pieces, cur = [], header
    for ln in lines[2:]:
        if len(cur) + len(ln) > limit and cur != header:
            pieces.append(cur)
            cur = header + "\n(continued)"
        cur += "\n" + ln
    pieces.append(cur)
    return pieces
