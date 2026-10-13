"""
The answer step: retrieved passages -> a grounded, cited answer.

Grounding is enforced in three places, not just asked for:
  * retrieval has a relevance floor, so weak passages never reach the prompt
  * if NOTHING passes the floor, Gemini is not called at all -- the reply is
    a fixed "not in the document" (no chance to hallucinate, no quota spent)
  * the prompt requires a [n] citation on every fact, so each claim in the
    answer can be checked against the source the UI shows next to it
"""

import time

from . import config, gemini
from .retrieval import retrieve

NOT_FOUND = (
    "I couldn't find this in the document. Try rephrasing, or ask about a topic, "
    "section or number that appears in it."
)

RULES = """You answer questions about ONE document: "{title}".

GROUNDING
- Use ONLY the numbered SOURCES below. No outside knowledge, no assumptions.
- If the sources do not contain the answer, say "The document doesn't say." and, if useful,
  mention what related information it does contain.
- Put a citation like [2] after every fact. Only cite sources that actually state that fact.

ACCURACY
- Copy numbers exactly as written, with their units, years and qualifiers ("more than", "about").
- Tables are written as rows: "label | value | value". Use the column-header row above to tell
  which year or column each value belongs to (e = estimate, f = forecast).
- Each source shows its section. When the question names a chapter, section, region or country,
  use only sources from that part; never mix figures from different regions or chapters.
- If a footnote under a source limits or explains a claim, include that caveat briefly.
- Do not calculate new numbers unless asked; if you do, show the calculation from cited values.

STYLE
- Lead with the direct answer in one or two sentences, then supporting details (bullets are fine).
- Keep it under ~200 words unless the question asks for more. Use plain markdown only -- no HTML tags.

SOURCES
{sources}"""


def _format_sources(passages: list[dict]) -> str:
    out = []
    for i, p in enumerate(passages, 1):
        pages = f"p. {p['page_start']}" if p["page_start"] == p["page_end"] else f"pp. {p['page_start']}-{p['page_end']}"
        kind = {"table": "TABLE", "figure": "FIGURE", "visual": "CHART (described from the page image)"}.get(p["kind"], "TEXT")
        out.append(f"[{i}] {kind} | Section: {p['section'] or '(none)'} | {pages}\n{p['text']}")
    return "\n\n".join(out)


def _search_query(message: str, history: list[dict]) -> str:
    """'and for 2027?' cannot be searched on its own. Rewrite short follow-ups
    into a standalone question -- one small extra Gemini call, only when needed."""
    if not history or not config.ENABLE_QUERY_REWRITE or len(message.split()) > 12:
        return message
    transcript = "\n".join(f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['text'][:400]}" for m in history[-4:])
    try:
        rewritten = gemini.generate(
            system="Rewrite the user's latest message as one standalone search question about the document. "
            "Keep names, regions, years and numbers. Reply with the question only.",
            message=f"Conversation:\n{transcript}\n\nLatest message: {message}\n\nStandalone question:",
            temperature=0,
        )
        return rewritten.strip().split("\n")[0][:300] or message
    except gemini.GeminiError:
        return message  # an optimisation, never a hard dependency


def answer(doc: dict, message: str, history: list[dict]) -> dict:
    t0 = time.time()
    query = _search_query(message, history)
    found = retrieve(doc["id"], query)
    passages = found["passages"]

    if not passages:
        text = NOT_FOUND
    else:
        text = gemini.generate(
            system=RULES.format(title=doc["title"] or doc["filename"], sources=_format_sources(passages)),
            message=message,
            history=history[-6:],
            temperature=0.2,
        )
    return {
        "answer": text,
        "searchQuery": query,
        "scope": found["scope"],
        "sources": passages,
        "candidates": found["candidates"],
        "timings_ms": {"retrieval": found["retrieval_ms"], "total": int((time.time() - t0) * 1000)},
    }
