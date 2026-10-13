"""
Charts -> text, with Gemini vision.

A chart's numbers are drawn, not written: the iMac carbon chart has the labels
"445 kg", "-99 kg" and "346 kg" as text, but what they MEAN (baseline, savings,
final footprint, and which coloured block is which) only exists in the picture.
So chart-heavy pages are rendered to an image and Gemini writes down what they
show. The description becomes a normal searchable chunk.

This is the only ingest step that uses the free quota, so it is limited to
short documents and capped per document, and every result is cached in
Postgres by (file hash, page, model).
"""

import pymupdf

from .. import config, db, gemini

PROMPT = """This is page {page} of a PDF report. Its body paragraphs are already indexed as text.
Describe ONLY the visual information on this page: charts, graphs, diagrams, tables drawn as
graphics, icon call-outs, infographics and labelled figures.

For every visual:
- name it (its title, or what it shows)
- list every number printed on it WITH its unit and exactly what it belongs to
  (e.g. "Baseline emissions: 445 kg CO2e")
- state the relationship the visual shows (comparison, breakdown, trend, steps)
- keep footnote markers as [n]

Rules:
- Only report values that are actually printed. If a segment has no printed value, say it is
  not labelled. Never estimate a number from bar lengths or areas.
- Plain text, short bullet points, no preamble.
- If the page has no meaningful visuals, reply with exactly: NONE"""


def pick_visual_pages(page_stats: list[dict], total_pages: int) -> list[int]:
    """Which pages are worth a vision call. Vector drawings (chart bars, icons)
    or a large image area mark a visual page."""
    if not config.ENABLE_VISION or total_pages > config.VISION_DOC_MAX_PAGES:
        return []
    visual = [p for p in page_stats if p["drawings"] >= 25 or p["image_ratio"] >= 0.15]
    visual.sort(key=lambda p: -(p["drawings"] + p["image_ratio"] * 100))
    return sorted(p["page"] for p in visual[: config.VISION_MAX_PAGES])


def describe_pages(path: str, sha: str, pages: list[int], on_progress=None) -> tuple[dict, dict]:
    """Returns ({page: description}, {"called": n, "cached": n, "failed": [...]})."""
    out, info = {}, {"called": 0, "cached": 0, "failed": []}
    doc = pymupdf.open(path)
    for i, pno in enumerate(pages):
        row = db.fetch_one(
            "SELECT description FROM vision_cache WHERE sha256=%s AND page=%s AND model=%s",
            (sha, pno, config.CHAT_MODEL),
        )
        if row:
            desc = row["description"]
            info["cached"] += 1
        else:
            png = doc[pno - 1].get_pixmap(dpi=120).tobytes("png")
            try:
                desc = gemini.generate(
                    system="You turn report pages into precise, factual text for a search index.",
                    message=PROMPT.format(page=pno),
                    image_png=png,
                    temperature=0,
                ).strip()
            except gemini.GeminiError as e:
                # Vision is an enhancement: the page's text is still indexed.
                info["failed"].append({"page": pno, "error": str(e)[:200]})
                continue
            info["called"] += 1
            db.execute(
                "INSERT INTO vision_cache (sha256, page, model, description) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING",
                (sha, pno, config.CHAT_MODEL, desc),
            )
        if desc and desc.upper() != "NONE":
            out[pno] = desc
        if on_progress:
            on_progress(i + 1, len(pages))
    return out, info
