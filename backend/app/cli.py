"""
Command-line access to the same pipeline the UI uses -- handy for poking at
one stage without clicking through the browser.

  python -m app.cli parse  file.pdf [--chunks]   parse + chunk only, print what was found
  python -m app.cli ingest file.pdf              full pipeline into Postgres
  python -m app.cli search <doc_id> "question"   retrieval only, no AI call
  python -m app.cli ask    <doc_id> "question"   full answer
"""

import hashlib
import json
import sys
from pathlib import Path

from . import config, db


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd, arg = sys.argv[1], sys.argv[2]

    if cmd == "parse":
        from .pipeline.chunk import build_chunks
        from .pipeline.parse import parse_pdf

        doc = parse_pdf(arg)
        chunks = build_chunks(doc, {})
        print(json.dumps(doc.stats), f"{len(chunks)} chunks")
        for e in doc.elements:
            if e.kind == "heading":
                print(f"p{e.page:<4}{'  ' * (e.level - 1)}{e.text}")
        if "--chunks" in sys.argv:
            for c in chunks:
                print(f"\n--- #{c.seq} {c.kind} p{c.page_start} {' > '.join(c.section_path)}\n{c.content}")
        return

    db.init_db()
    if cmd == "ingest":
        from .pipeline.run import run_pipeline

        data = Path(arg).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        config.UPLOAD_DIR.mkdir(exist_ok=True)
        path = config.UPLOAD_DIR / f"{sha}.pdf"
        path.write_bytes(data)
        row = db.fetch_one(
            "INSERT INTO documents (sha256, filename) VALUES (%s,%s) "
            "ON CONFLICT (sha256) DO UPDATE SET status='processing', error=NULL RETURNING id",
            (sha, Path(arg).name),
        )
        run_pipeline(row["id"], str(path), sha)
        d = db.fetch_one("SELECT id, status, error, progress, profile FROM documents WHERE id=%s", (row["id"],))
        for stage, info in d["progress"].items():
            print(f"{stage:<7} {info.get('status'):<8} {info.get('ms', 0):>6} ms  {info.get('detail', '')}")
        print(f"document id {d['id']}: {d['status']} {d['error'] or ''}")
    elif cmd in ("search", "ask"):
        question = sys.argv[3]
        if cmd == "search":
            from .retrieval import retrieve

            r = retrieve(int(arg), question)
        else:
            from .rag import answer

            doc = db.fetch_one("SELECT * FROM documents WHERE id=%s", (int(arg),))
            r = answer(doc, question, [])
            print(r["answer"], "\n")
        print("scope:", r["scope"])
        for i, p in enumerate(r.get("sources") or r["passages"], 1):
            print(f"[{i}] {p['score']:>6} {p['kind']:<6} p{p['page_start']} {p['section'][-70:]}")
            if cmd == "search":
                print("     " + p["text"][:300].replace("\n", " ") + "\n")


if __name__ == "__main__":
    main()
