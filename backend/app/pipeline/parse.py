"""
PDF -> a flat, reading-ordered list of typed Elements.

This is where the three documents stop looking alike. Plain text extraction
(`pdftotext`) turns all of them into one long string and loses exactly what
matters:

  * headings      -> without them, "South Asia" and "Sub-Saharan Africa"
                     growth paragraphs are indistinguishable
  * tables        -> extracted column-by-column, a forecast table becomes a
                     useless list of numbers with no row labels
  * footnotes     -> "58 percent less energy than ENERGY STAR.18" loses note 18,
                     which says what the comparison was measured against
  * running headers/footers -> "iMac | Product Environmental Report 7" repeated
                     on every page pollutes every chunk

So instead of reading text, we read LAYOUT: every line comes with its font,
size, position and flags, and each step below uses those to decide what a
line is. Nothing here is specific to the three test documents; each step
simply finds nothing to do on a document that lacks that feature.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pymupdf


@dataclass
class Line:
    text: str
    size: float
    font: str
    bold: bool
    bbox: tuple
    page: int  # 1-based
    refs: list = field(default_factory=list)  # footnote numbers (superscripts)
    italic: bool = False

    @property
    def style(self):
        return (round(self.size * 2) / 2, self.bold)


@dataclass
class Element:
    kind: str  # heading | text | table | figure | note | visual
    text: str
    page: int
    level: int = 0  # headings only: 1 = top level
    refs: list = field(default_factory=list)
    num: str | None = None  # notes only: the footnote number


@dataclass
class ParsedDoc:
    title: str
    pages: int
    elements: list
    notes: dict  # footnote number -> text (document-level endnotes)
    page_stats: list  # per page: chars, drawings, image_ratio
    stats: dict  # counts for the UI


BOLD_HINTS = ("bold", "black", "heavy", "semibold", "demi", "-md", "medium")
CAPTION_RE = re.compile(r"^(TABLE|Table|FIGURE|Figure)\s+[A-Z]?\d+(\.\d+)*[A-Z]?\b")
NUMERIC_CELL_RE = re.compile(
    r"^[(\-–−+$€£<>~≈↓↑]*\s*\d[\d,.]*\s*(%|percent|kg|g|kWh|W|million|billion|"
    r"thousand|CO2e|CO₂e|[a-zA-Z]{0,3})?\)?\s*\S{0,12}$"
)
NOTES_HEADING_RE = re.compile(r"^(end\s*notes|notes|footnotes)$", re.I)


def _is_bold(span) -> bool:
    return bool(span["flags"] & 16) or any(h in span["font"].lower() for h in BOLD_HINTS)


# ---------------------------------------------------------------------------
# 1. Read every line with its style
# ---------------------------------------------------------------------------


def _read_lines(page, pno: int) -> list[Line]:
    lines = []
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
        for raw in block.get("lines", []):
            for spans in _split_run_in(raw["spans"]):
                ln = _make_line(spans, raw["bbox"], pno)
                if ln:
                    lines.append(ln)
    return lines


def _split_run_in(spans):
    """'Federal Depository Library Program  The FDLP links ...' is a run-in
    heading: a bold/other-font title followed on the SAME line by body text.
    Split it at the style change so the title can be recognised.
    Whitespace-only spans are kept: a tab is often the only thing between an
    endnote's number and its text."""
    real = [i for i, s in enumerate(spans) if s["text"].strip() and not s["flags"] & 1]
    if len(real) < 2:
        return [spans]
    first = spans[real[0]]
    for i in real[1:]:
        s = spans[i]
        if s["font"] != first["font"] or abs(s["size"] - first["size"]) > 0.5:
            head = "".join(x["text"] for x in spans[:i]).strip()
            if 2 <= len(head.split()) <= 10 and _is_bold(first) and not head.endswith((",", ";")):
                return [spans[:i], spans[i:]]
            break
    return [spans]


def _make_line(spans, line_bbox, pno: int) -> Line | None:
    real = [s for s in spans if s["text"].strip()]
    if not real:
        return None
    # The dominant span (most characters) decides the line's style, so one
    # bold word inside a sentence does not make it a heading.
    main = max(real, key=lambda s: len(s["text"].strip()))
    text, refs = "", []
    for s in spans:
        t = s["text"]
        # Superscript flag (1) on a short number = a footnote marker.
        if s["flags"] & 1 and re.fullmatch(r"\s*\d{1,3}(,\d{1,3})*\s*", t):
            nums = [n.strip() for n in t.split(",") if n.strip()]
            refs += nums
            text = text.rstrip() + "".join(f"[{n}]" for n in nums) + " "
        else:
            text += t
    text = re.sub(r"\s+", " ", text.replace("\t", " ")).strip()
    if not text:
        return None
    x0 = min(s["bbox"][0] for s in real)
    x1 = max(s["bbox"][2] for s in real)
    bbox = (x0, line_bbox[1], x1, line_bbox[3])
    italic = bool(main["flags"] & 2) or "italic" in main["font"].lower() or main["font"].endswith("It")
    return Line(text, main["size"], main["font"], _is_bold(main), bbox, pno, refs, italic)


# ---------------------------------------------------------------------------
# 2. Running headers / footers
# ---------------------------------------------------------------------------


def _margin_keys(all_pages: list[list[Line]], heights: list[float]) -> set:
    """Text in the top/bottom 8% of the page that repeats on 3+ pages."""
    seen = defaultdict(set)
    for lines, h in zip(all_pages, heights):
        for ln in lines:
            if ln.bbox[1] < h * 0.08 or ln.bbox[3] > h * 0.92:
                seen[_margin_key(ln.text)].add(ln.page)
    return {k for k, pages in seen.items() if len(pages) >= 3}


def _margin_key(text: str) -> str:
    return re.sub(r"\d+", "#", text.lower().replace(" ", ""))


def _is_margin(ln: Line, h: float, keys: set) -> bool:
    if not (ln.bbox[1] < h * 0.08 or ln.bbox[3] > h * 0.92):
        return False
    return _margin_key(ln.text) in keys or re.fullmatch(r"[\divxlc]+", ln.text.lower()) is not None


# ---------------------------------------------------------------------------
# 3. Tables, rebuilt row by row from word positions
# ---------------------------------------------------------------------------


def _rows(words, region=None, tol=3.0):
    """Group words into visual rows (same baseline) and rows into cells (big
    horizontal gaps). Returns [(y, x0, x1, [cell, ...])]."""
    if region:
        x0, y0, x1, y1 = region
        words = [w for w in words if w[0] >= x0 - 2 and w[2] <= x1 + 2 and w[1] >= y0 - 2 and w[3] <= y1 + 2]
    rows = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        yc = (w[1] + w[3]) / 2
        if rows and abs(rows[-1][0] - yc) < tol:
            rows[-1][1].append(w)
        else:
            rows.append([yc, [w]])
    out = []
    for yc, ws in rows:
        ws.sort(key=lambda w: w[0])
        cells, prev_x1 = [], None
        for w in ws:
            gap_limit = max(6.0, (w[3] - w[1]) * 0.9)  # ~ one character height
            if prev_x1 is None or w[0] - prev_x1 > gap_limit:
                cells.append([])
            cells[-1].append(w[4])
            prev_x1 = w[2]
        out.append((yc, ws[0][0], max(w[2] for w in ws), [" ".join(c) for c in cells]))
    return out


def _caption_regions(lines: list[Line], page_w: float, page_h: float, body_size: float):
    """GEP-style captioned tables and figures: from the 'TABLE 2.9 ...' line down
    to its 'Source(s):' line plus the small-print notes under it."""
    regions = []
    ordered = sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0]))
    for i, cap in enumerate(ordered):
        m = CAPTION_RE.match(cap.text)
        if not m or len(cap.text) > 160:
            continue
        # Body prose like "Table 2.9 shows that..." is not a caption: real
        # captions are set apart in a different style.
        if abs(cap.size - body_size) < 0.3 and not cap.bold and cap.text[m.end():m.end() + 1] not in (" ", ""):
            continue
        left_col = cap.bbox[0] < page_w * 0.45
        x0 = cap.bbox[0] - 4
        source, end_y = None, None
        for ln in ordered[i + 1 :]:
            if ln.bbox[0] < x0 - 4 and ln.bbox[2] < cap.bbox[0]:
                continue  # other column
            if CAPTION_RE.match(ln.text) and ln.bbox[1] > cap.bbox[3] + 5:
                break  # the next table starts
            if re.match(r"^Sources?\s*:", ln.text):
                source = ln
                end_y, right = ln.bbox[3], ln.bbox[2]
                continue
            if source is not None:
                # Notes under the source line: smaller print, no big gap.
                if ln.size <= body_size * 0.9 and ln.bbox[1] - end_y < 14:
                    end_y, right = ln.bbox[3], max(right, ln.bbox[2])
                    continue
                break
        if source is None:
            continue
        # Table width = the widest small-print line between caption and notes.
        # Body-size lines in that band belong to the neighbouring text column.
        for ln in ordered:
            if cap.bbox[1] <= ln.bbox[1] <= end_y and ln.bbox[0] >= x0 - 4 and ln.size < body_size * 0.95:
                right = max(right, ln.bbox[2])
        x1 = max(cap.bbox[2], right)
        if left_col and x1 < page_w * 0.55:
            x1 = max(x1, page_w * 0.5 - 4)
        elif x1 > page_w * 0.55:
            x1 = page_w
        kind = "table" if m.group(1).lower() == "table" else "figure"
        regions.append((kind, (x0, cap.bbox[1] - 1, x1, end_y + 1), cap))
    return regions


def _cell_is_numeric(cell: str) -> bool:
    return bool(NUMERIC_CELL_RE.match(cell.strip())) and any(c.isdigit() for c in cell)


def _grid_regions(words, taken, page_h: float):
    """Uncaptioned tables (iMac, GPO): runs of 2+ rows that each have 2+ short
    cells, at least one of them a number. Two-column prose never qualifies,
    because each 'cell' would be a whole line of text."""
    free = [w for w in words if not any(_inside(w, r) for r in taken)]
    rows = _rows(free)

    def tabular(r):
        cells = r[3]
        if len(cells) < 2 or not any(_cell_is_numeric(c) for c in cells):
            return False
        # "Apple emissions from utility-purchased electricity (scope 2) | 0 kg"
        # is a label/value row even though the label is long.
        if len(cells) == 2 and _cell_is_numeric(cells[1]):
            return len(cells[0]) <= 80
        return all(len(c) <= 40 for c in cells)

    regions, run = [], []
    for r in rows + [None]:
        if r is not None and tabular(r) and (not run or r[0] - run[-1][0] < 40):
            run.append(r)
            continue
        if len(run) >= 2:
            # Pull in header rows directly above (short multi-cell labels).
            first = rows.index(run[0])
            head = []
            for prev in reversed(rows[max(0, first - 2) : first]):
                if len(prev[3]) >= 2 and all(len(c) <= 40 for c in prev[3]) and run[0][0] - prev[0] < 40:
                    head.insert(0, prev)
                else:
                    break
            members = head + run
            ys = [m[0] for m in members]
            regions.append(
                ("table", (min(m[1] for m in members) - 2, min(ys) - 8, max(m[2] for m in members) + 2, max(ys) + 8), None)
            )
        run = [r] if r is not None and tabular(r) else []
    return regions


def _inside(item, region) -> bool:
    """item is a word tuple or a bbox; inside if its centre is in the region."""
    x0, y0, x1, y1 = item[:4]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx0, ry0, rx1, ry1 = region[1] if isinstance(region[0], str) else region
    return rx0 <= cx <= rx1 and ry0 <= cy <= ry1


def _table_text(words, region, caption: Line | None) -> str:
    rows = _rows(words, region)
    out = []
    for _, _, _, cells in rows:
        line = " | ".join(cells)
        if caption is not None and line.startswith(caption.text[:20]):
            continue  # the caption is printed separately on top
        out.append(line)
    head = f"{caption.text}\n" if caption is not None else ""
    return head + "\n".join(out)


# ---------------------------------------------------------------------------
# 4. Headings
# ---------------------------------------------------------------------------


def _heading_levels(candidates: list[Line]) -> dict:
    """Rank the distinct heading styles: biggest = level 1. Very large display
    sizes (chapter openers) all share level 1."""
    sizes = sorted({c.style for c in candidates}, key=lambda s: (-s[0], not s[1]))
    levels, level = {}, 0
    for st in sizes:
        if level == 0 or st[0] < 22:
            level += 1
        levels[st] = level if st[0] < 22 else 1
    return levels


SMALL_WORDS = {"of", "in", "to", "and", "the", "a", "an", "for", "on", "at", "by"}


def _title_case(text: str) -> str:
    """'A RISING CHALLENGE' -> 'A Rising Challenge', keeping FY / EMDEs / III."""
    if text.isupper() and len(text) > 3:
        words = []
        for i, w in enumerate(text.split()):
            if len(w) <= 2 or re.fullmatch(r"[IVX]+", w) or w in ("EMDE", "EMDES", "GDP"):
                words.append(w.replace("EMDES", "EMDEs"))
            elif i > 0 and w.lower() in SMALL_WORDS:
                words.append(w.lower())
            else:
                words.append(w.capitalize())
        text = " ".join(words)
    return re.sub(r"^(Chapter \d+)\s+(?!:)", r"\1: ", text, flags=re.I)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def parse_pdf(path: str) -> ParsedDoc:
    doc = pymupdf.open(path)
    n = len(doc)
    all_lines = [_read_lines(doc[i], i + 1) for i in range(n)]
    heights = [doc[i].rect.height for i in range(n)]
    margin_keys = _margin_keys(all_lines, heights)

    # Body style per PAGE, not per document: GPO is a narrative report in 9.8pt
    # Garamond glued to financial statements in 12pt Helvetica.
    def body_of(lines):
        c = Counter()
        for ln in lines:
            c[(round(ln.size, 1), ln.font)] += len(ln.text)
        return c.most_common(1)[0][0] if c else (10.0, "")

    doc_body = body_of([ln for page_lines in all_lines for ln in page_lines])
    elements: list[Element] = []
    page_stats = []
    stats = Counter()

    for i in range(n):
        page = doc[i]
        pno = i + 1
        w, h = page.rect.width, page.rect.height
        lines = [ln for ln in all_lines[i] if not _is_margin(ln, h, margin_keys)]
        # A chapter-opener page is nothing but a big title; its "most common
        # style" is the title itself. Too little text -> use the document's.
        page_body = body_of(lines)
        body_chars = sum(len(ln.text) for ln in lines if (round(ln.size, 1), ln.font) == page_body)
        body_size, body_font = page_body if body_chars >= 400 else doc_body

        # Page statistics -- used later to decide which pages are visual.
        drawings = len(page.get_drawings())
        img_area = 0.0
        for info in page.get_image_info():
            x0, y0, x1, y1 = info["bbox"]
            img_area += max(0, x1 - x0) * max(0, y1 - y0)
        chars = sum(len(ln.text) for ln in lines)
        page_stats.append({"page": pno, "chars": chars, "drawings": drawings, "image_ratio": round(img_area / (w * h), 2)})

        # --- regions: captioned tables/figures first, then uncaptioned grids --
        words = [wd for wd in page.get_text("words") if not _is_margin_word(wd, h)]
        regions = _caption_regions(lines, w, h, doc_body[0])
        regions += _grid_regions(words, [r[1] for r in regions], h)

        region_elems = []
        for kind, box, cap in regions:
            if kind == "table":
                text = _table_text(words, box, cap)
                stats["tables"] += 1
            else:
                # Figures: keep caption, panel titles, notes and sources; drop
                # axis ticks and data labels (lines of < 4 words).
                inner = [ln.text for ln in lines if _inside(ln.bbox, box) and (ln is cap or len(ln.text.split()) >= 4)]
                text = "\n".join(inner)
                stats["figures"] += 1
            refs = [r for ln in lines if _inside(ln.bbox, box) for r in ln.refs]
            region_elems.append((box, Element(kind, text, pno, refs=refs)))

        # --- prose lines, grouped back into paragraphs ----------------------
        prose = [ln for ln in lines if not any(_inside(ln.bbox, r[1]) for r in regions)]
        page_elems = []
        para: list[Line] = []

        def flush():
            if para:
                box = (min(l.bbox[0] for l in para), para[0].bbox[1], max(l.bbox[2] for l in para), para[-1].bbox[3])
                page_elems.append((box, _paragraph(para)))
                para.clear()

        for idx, ln in enumerate(prose):
            # A heading wrapped onto a second line ("Carbon" / "Footprint",
            # "Made with smarter" / "chemistry") is one heading.
            last = page_elems[-1][1] if page_elems and not para else None
            if last is not None and last.kind == "heading" and _continues_heading(last._line, ln):
                box = page_elems[-1][0]
                last.text += " " + ln.text
                last._line = ln
                page_elems[-1] = ((box[0], box[1], max(box[2], ln.bbox[2]), ln.bbox[3]), last)
                continue
            if _looks_like_heading(ln, body_size, body_font, prose, idx):
                flush()
                head = Element("heading", ln.text, pno)
                head._line = ln  # its style decides the level, assigned below
                page_elems.append((ln.bbox, head))
                continue
            if para and _new_paragraph(para[-1], ln):
                flush()
            para.append(ln)
        flush()

        elements.extend(_reading_order(page_elems + region_elems, w))

    # --- heading levels + merging stacked display titles ----------------------
    heads = [e for e in elements if e.kind == "heading"]
    levels = _heading_levels([e._line for e in heads])
    merged: list[Element] = []
    for e in elements:
        if e.kind == "heading":
            e.level = levels[e._line.style]
            prev = merged[-1] if merged else None
            # "CHAPTER 3" / "A RISING CHALLENGE" / "Sovereign Debt ..." are one title.
            if (
                prev is not None
                and prev.kind == "heading"
                and prev.page == e.page
                and e._line.size >= 18
                and prev._line.size >= 18
            ):
                # A new type size starts a new part of the title ("Chapter 3" /
                # "A Rising Challenge"); the same size is a wrapped line.
                sep = " " if prev._line.style == e._line.style else ": "
                prev.text = f"{_title_case(prev.text)}{sep}{_title_case(e.text)}"
                prev._line = e._line
                continue
        merged.append(e)
    for e in merged:
        if e.kind == "heading":
            bare = re.sub(r"\[\d+\]", "", e.text).strip()
            if bare.endswith(".") or len(bare.split()) > 16:
                e.kind = "text"  # a multi-line big-print statement, not a title
            else:
                e.text = _title_case(e.text.strip())
    stats["headings"] = sum(1 for e in merged if e.kind == "heading")
    stats["heading_levels"] = len({e.level for e in merged if e.kind == "heading"})

    # --- footnotes -------------------------------------------------------------
    merged, notes = _collect_notes(merged)
    stats["notes"] = len(notes)
    stats["note_refs"] = sum(len(e.refs) for e in merged)

    title = (doc.metadata or {}).get("title") or ""
    return ParsedDoc(title.strip(), n, merged, notes, page_stats, dict(stats))


def _is_margin_word(wd, h) -> bool:
    return wd[1] < h * 0.06 or wd[3] > h * 0.94


def _looks_like_heading(ln: Line, body_size: float, body_font: str, prose: list[Line], idx: int) -> bool:
    words = ln.text.split()
    if not (1 <= len(words) <= 14) or len(ln.text) > 110 or not re.search(r"[A-Za-z]{2}", ln.text):
        return False
    bare = re.sub(r"\[\d+\]", "", ln.text).strip()
    if CAPTION_RE.match(bare):
        return False
    if re.search(r"\d", bare) and (sum(c.isalpha() for c in bare) < 5 or bare.endswith("%")):
        return False  # "445 kg", "Over 20%": big-print numbers are facts, not titles
    big_bold = ln.bold and ln.size >= body_size * 1.25
    if bare.endswith((",", ";")) and not big_bold:  # "Middle East, North Africa," wraps
        return False
    if ln.size < body_size * 0.95 or bare.endswith(".") or bare[:1].islower():
        # Ends like a sentence or continues one: a big-print statement such as
        # "iMac uses 58 percent less energy than ENERGY STAR." is a FACT and
        # belongs in the chunk text, not in the section path.
        return False
    big = ln.size >= body_size * 1.15
    if ln.italic and not ln.bold and not big:
        return False  # italic = a publication title or emphasis, not a heading
    distinct = ln.bold or _family(ln.font) != _family(body_font)
    if not (big or distinct):
        return False
    if re.search(r"(\.{4,}|…{2,})", ln.text):
        return False  # a table-of-contents entry
    if ln.size >= body_size * 1.6 or (ln.bold and ln.size >= body_size * 1.25):
        return True  # display-size or big bold titles need no further evidence
    # A heading starts fresh: if the line right above is body text in the same
    # column, this is an italic book title or emphasis inside a paragraph.
    if idx > 0:
        prev = prose[idx - 1]
        gap = ln.bbox[1] - prev.bbox[3]
        if prev.font == body_font and abs(prev.bbox[0] - ln.bbox[0]) < 20 and -1 <= gap < ln.size * 0.5 and not prev.text.endswith((".", ":")):
            return False
    # The deciding test for small headings: they introduce body text. Chart
    # labels in a different font are followed by more chart labels.
    for nxt in prose[idx + 1 : idx + 4]:
        if abs(nxt.size - ln.size) < 0.05 and nxt.font == ln.font and nxt.bold == ln.bold:
            continue  # the heading wraps onto a second line
        return abs(nxt.size - body_size) < 0.6 and nxt.font == body_font
    return False


def _family(font: str) -> str:
    return font.split("-")[0].split(",")[0]


def _continues_heading(prev: Line, ln: Line) -> bool:
    gap = ln.bbox[1] - prev.bbox[3]
    return (
        ln.style == prev.style
        and ln.font == prev.font
        and abs(ln.bbox[0] - prev.bbox[0]) < 6  # same left edge, not a neighbour column
        and -ln.size * 0.5 <= gap < ln.size * 0.8  # big type has overlapping line boxes
        and len(ln.text) < 80
    )


def _new_paragraph(prev: Line, ln: Line) -> bool:
    gap = ln.bbox[1] - prev.bbox[3]
    if ln.page != prev.page or abs(ln.size - prev.size) > 0.6:
        return True
    if gap > prev.size * 0.9 or gap < -prev.size * 3:  # big gap, or jumped to a new column
        return True
    return re.match(r"^(•|·|–|-|\d+[.)])\s", ln.text) is not None


def _paragraph(lines: list[Line]) -> Element:
    text = ""
    for ln in lines:
        t = ln.text
        if text.endswith("-") and t[:1].islower():
            text = text[:-1] + t  # re-join a hyphenated word
        else:
            text = f"{text} {t}" if text else t
    return Element("text", text, lines[0].page, refs=[r for ln in lines for r in ln.refs])


def _reading_order(items, page_w: float):
    """Order a page's (bbox, element) pairs the way a person reads them.

    Items that cross the middle of the page (titles, full-width tables, single
    column text) are read top to bottom and act as dividers; between two
    dividers, the left column is read before the right one. Handles one- and
    two-column layouts, which covers most reports.
    """
    mid = page_w / 2
    full = sorted((it for it in items if it[0][0] < mid - 10 and it[0][2] > mid + 10), key=lambda it: it[0][1])
    side = [it for it in items if not (it[0][0] < mid - 10 and it[0][2] > mid + 10)]
    out, top = [], float("-inf")
    for divider in full + [None]:
        bottom = divider[0][1] if divider else float("inf")
        seg = [it for it in side if top <= it[0][1] < bottom]
        seg.sort(key=lambda it: (0 if it[0][2] <= mid + 10 else 1, it[0][1]))
        out += [e for _, e in seg]
        if divider:
            out.append(divider[1])
            top = bottom
    return out


def _collect_notes(elements: list[Element]) -> tuple[list[Element], dict]:
    """Endnotes: the text under an 'Endnotes' / 'Notes' heading is split into
    numbered notes. Returns the elements with that section replaced by one
    'note' element per note, plus a number -> text map the chunker uses to
    attach each note to the sentences that cite it.

    Numbers are accepted only in sequence (1, 2, 3 ...), so "ISO 14040" or
    "3) Apple's average mix" inside a note never starts a new one.
    """
    out: list[Element] = []
    notes: dict[str, str] = {}
    section: list[Element] = []

    def close():
        if not section:
            return
        text = " ".join(e.text for e in section)
        text = re.sub(r"\[(\d{1,3})\]", r" \1 ", text)  # superscript-styled numbers
        expected = int(list(notes)[-1]) + 1 if notes else 1
        starts = []
        pos = 0
        while True:
            m = re.compile(rf"(?:^|\s){expected}\s+(?=[A-Za-z“\"(])").search(text, pos)
            if not m:
                break
            starts.append((expected, m.start(), m.end()))
            pos, expected = m.end(), expected + 1
        if not starts:
            out.extend(section)  # not a numbered list after all
        for i, (num, _, body_start) in enumerate(starts):
            body_end = starts[i + 1][1] if i + 1 < len(starts) else len(text)
            notes[str(num)] = text[body_start:body_end].strip()
            out.append(Element("note", f"[{num}] {notes[str(num)]}", section[0].page, num=str(num)))
        section.clear()

    in_notes = False
    for e in elements:
        if e.kind == "heading":
            close()
            in_notes = bool(NOTES_HEADING_RE.match(e.text.strip()))
            out.append(e)
        elif in_notes and e.kind == "text":
            section.append(e)
        else:
            out.append(e)
    close()
    return out, notes
