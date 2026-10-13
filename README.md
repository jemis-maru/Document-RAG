# 📄 Doc RAG — one pipeline, three document shapes

Upload a PDF, then ask questions that are answered **only from that PDF**, with every fact
cited to its section and page. Built for the Advanced RAG exercise with three
deliberately different documents:

| # | Document | Shape | What breaks a naive RAG |
|---|---|---|---|
| 1 | GPO 2018 Annual Report (82 p) | Narrative text | Not much — the baseline |
| 2 | World Bank Global Economic Prospects, June 2026 (200 p) | Long & structured | Regions/chapters look alike; tables come out as columns of loose numbers |
| 3 | Apple iMac Product Environmental Report (12 p) | Visual | Facts live in charts, tables, call-outs and footnotes |

Next.js (frontend) · FastAPI (backend) · Postgres + pgvector · local embeddings & reranker · Gemini free tier

---

## Setup

### 1. Postgres (the same server as the AI RAG project)

```bash
sudo systemctl start postgresql
createdb -h localhost -U bacancy docrag                       # password: devpass
sudo -u postgres psql -d docrag -c "CREATE EXTENSION vector;" # needs superuser, once
```

Tables are created by the backend on first start.

### 2. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU-only build, ~200 MB
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # paste your free Gemini key: https://aistudio.google.com/apikey
.venv/bin/uvicorn app.main:app --reload --port 8000
```

On first use the two local models download from Hugging Face (~220 MB) and are cached in
`~/.cache/huggingface`.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev                 # http://localhost:3200
```

Open <http://localhost:3200>, upload one of the PDFs from [documents/](documents/), wait for processing, ask questions.
**New chat** goes back to the upload screen. Uploading a file that was processed before is instant.

---


## How it works — the big picture

Think of the PDF as a **big textbook** and the app as a **smart librarian**.

The librarian works in two phases:

1. **Prepare the book (once, when you upload):** read it carefully, cut it into small
   labelled pieces, and build an index so any piece can be found fast.
2. **Answer a question (every time you ask):** find the few pieces that answer it, then write
   an answer using **only** those pieces — and say which page each fact came from.

```
PREPARE (once per file)
PDF ─▶ parse ─▶ detect ─▶ vision ─▶ chunk ─▶ embed ─▶ store

ANSWER (every question)
question ─▶ scope ─▶ hybrid search ─▶ fuse ─▶ rerank ─▶ floor ─▶ expand ─▶ Gemini ─▶ cited answer
```

---

## Part 1 — Preparing the document

### 1. Parse — read the PDF *with its layout*

Plain text extraction turns a PDF into one long string and loses what matters. Instead, the
parser reads every line **with its font, size and position**, and uses that to tell what each
line is:

| It finds | How | Why it matters |
|---|---|---|
| **Headings** | Bigger or bolder than the normal text around it | Every piece later knows which chapter/section it belongs to |
| **Tables** | Words lined up in rows and columns | Rebuilt row by row: `India \| 7.2 \| 7.1 \| 7.7`. Plain extraction would output a useless column of numbers |
| **Footnotes** | Small raised numbers like ¹⁸ and the numbered notes at the end | The note that explains a claim stays with the claim |
| **Page headers/footers** | Same text repeated at the top/bottom of many pages | Removed — "iMac \| Product Environmental Report 7" on every page is noise |

### 2. Detect — what kind of document is this?

From simple counts (pages, headings, graphics per page) — no AI — the document is labelled
**Narrative**, **Long & structured** or **Visual**. You see this label in the app.

### 3. Vision — read the charts

A chart's meaning lives in the picture, not the text. For **short** documents (≤ 40 pages),
pages full of charts are sent to Gemini as images, and Gemini writes down what they show
("Baseline emissions: 445 kg …"). This is saved, so the same page is never sent twice.

Long documents skip this — their charts have captions and notes, and 200 pages would use up
the free quota.

### 4. Chunk — cut the document into small pieces

**Why cut it up at all?**

- **Search needs small pieces.** A search compares your question with each piece. One giant
  piece would match every question a little and none of them well — like a book with no index.
- **The AI should read only what's relevant.** Sending all 200 pages for every question is slow,
  burns quota, and the AI misses facts buried in so much text. Six good pieces work better.
- **Citations need small pieces.** Each piece remembers its section and page, so an answer can
  say *"p. 96"* instead of *"somewhere in these 200 pages"*.

**The cutting rules:**

| Rule | Why |
|---|---|
| About 1,200 characters per piece (a paragraph or two) | Small enough to be about one thing, big enough to make sense alone |
| Never cut across a heading | A piece is never half "South Asia", half "Africa" |
| Each piece keeps its **section path**, e.g. `Chapter 2 > South Asia > Outlook` | The piece "knows" where it lives, even if its text only says "SAR" |
| Neighbouring pieces overlap by ~200 characters | A fact cut at the edge is still whole in one of them |
| A table is its own piece and is never cut mid-row | Numbers stay next to their labels and column headers |
| Footnotes are attached to the piece that cites them | "58% less energy[18]" carries note 18 with it |

Example — one real piece from the World Bank report:

```
section:  Chapter 2: Regional Outlooks > South Asia > Outlook
page:     96
text:     "Growth in SAR is expected to soften to 6.3 percent in 2026, mainly
           reflecting the adverse impact of the conflict in the Middle East…"
```

The World Bank report becomes ~815 pieces; the iMac report ~50.

### 5. Embed — turn each piece into numbers that capture its meaning

Computers can't compare meanings, but they can compare numbers. A small AI model (running on
your computer, no quota) reads each piece and outputs **384 numbers** — a kind of
*meaning fingerprint*:

```
"Growth in SAR is expected to soften…"  →  [-0.001, -0.053, 0.020, -0.025, 0.073, …]
```

No single number means anything. What matters: **pieces with similar meaning get similar
numbers.** Your question gets a fingerprint too, so the closest pieces can be found:

| Piece | Similarity to *"What is the growth outlook for South Asia?"* |
|---|---|
| South Asia › Outlook: "Growth in SAR is expected to soften to 6.3%…" | **0.80** |
| Sub-Saharan Africa › Outlook: "Growth in SSA is forecast to edge down…" | 0.74 |
| Acknowledgments: "This report is a product of the Prospects Group…" | 0.58 |

The South Asia piece wins even though it says "SAR" — because the section path is fingerprinted
together with the text. But notice Africa is close behind: both are "growth forecast"
paragraphs. Meaning alone isn't enough — that's why the next steps exist.

### 6. Store — save everything in Postgres

Each piece is saved with its text, section, page, its 384 numbers (for meaning search), and a
word index (for exact-word search).

---

## Part 2 — Answering a question

We'll follow one question all the way through:

> **"What is the growth outlook for South Asia?"** — asked about the World Bank report

### Step 1. Scope — *where* should we look?

**Scope = pick the right chapter before you start looking.**

The question's words are compared with the document's **section titles**. "South Asia" is a
section title, so the search is limited to pieces inside the South Asia section.

Why? Every region in the report is written the same way — *"Growth is expected to slow…
risks remain to the downside…"*. Searching the whole book, Africa's paragraph sounds just as
right as South Asia's, and the answer could mix them up. Scope makes that impossible.

| Question | Scope |
|---|---|
| "Growth outlook for **South Asia**?" | Only the South Asia section |
| "What does **Chapter 3** say about debt?" | Only Chapter 3 |
| "According to the **executive summary**, what are the risks?" | Only the Executive Summary |
| "How many libraries did GPO visit?" | No section named → whole document |

- Generic words like "Outlook" or "Risks" never trigger a scope — they appear in every region.
- If the chosen section has nothing relevant, the search falls back to the whole document.

### Step 2. Hybrid search — *how* do we look? Two ways at once

Inside the scoped area, two searches run side by side. Each is good at what the other is bad at:

| | Meaning search (vector) | Word search (keyword) |
|---|---|---|
| Works like | Understanding the question | Ctrl+F |
| Good at | Different words, same idea: "power use" finds "energy consumption" | Exact names and numbers: "FDsys", "ENERGY STAR", "802,834" |
| Bad at | Exact names and numbers | Synonyms — "power" will never find "energy" |

Each search returns its own ranked list of ~30 pieces.

> **Scope vs hybrid search:** scope decides **where** to look (which chapter, using headings);
> hybrid search decides **which paragraphs** in there match best (using the text itself).

### Step 3. Fuse — merge the two lists into one

The two searches score in different units (like marks out of 10 vs marks out of 100), so their
scores can't be added. Fuse uses **positions** instead:

- Every position earns points — 1st place the most, 2nd a bit less, and so on.
- A piece's points from both lists are added up. (Not in a list = 0 points from it.)
- Sorted by total: high in **both** lists → top; high in one only → middle.

| Piece | Meaning search | Word search | After fuse |
|---|---|---|---|
| "Growth is then anticipated to rebound…" | 1st | 1st | **1st** |
| "With conflict-related disruptions assumed to wane…" | 2nd | 3rd | **2nd** |
| "TABLE 2.9 South Asia forecast summary…" | 3rd | 2nd | **3rd** |
| "Growth in SAR is expected to soften to 6.3%…" | 5th | 5th | **4th** |

(The 2nd and 3rd pieces earn exactly the same points — 2nd + 3rd vs 3rd + 2nd — so they tie.)

Like two judges ranking contestants: you don't compare how each judge marks, you reward
whoever both judges placed near the top. Fuse is quick, but it **never reads the text** — it
only looks at positions.

### Step 4. Rerank — read each piece carefully with the question

Now a second small AI model (the *reranker*, also on your computer) **reads the question and
each of the ~30 pieces together** and gives each one a score for *"does this actually answer
the question?"*

Why is this better than the meaning search?

- **Meaning search** fingerprints the question and the piece *separately*, then compares
  fingerprints — like judging a book by its back cover.
- **Reranker** reads them *side by side* — like opening the book to that page with your
  question in mind.

| Score | Piece | Position before |
|---|---|---|
| **8.1** | "Growth in SAR is expected to soften to **6.3 percent in 2026**…" | 4th |
| 7.4 | "Growth is then anticipated to rebound…" | 1st |
| 7.1 | "…pick up to an average of **7 percent per year in 2027–28**" | 2nd |

The piece with the actual answer moved from **4th to 1st**.

It reads **all ~30**, not just the first few — the best answer is often lower in the merged list.
It doesn't read all 815 pieces because careful reading is slow; steps 2–3 shortlist first.

> **Hiring analogy:** hybrid search = two recruiters screening CVs · fuse = merging their
> shortlists · rerank = interviewing everyone on the shortlist.

### Step 5. Floor — no good piece, no answer

Pieces scoring below **−4** are dropped; the best **6** are kept.

If **nothing** passes — e.g. *"Who won the 2018 World Cup?"* (best score −10) — the app answers
*"I couldn't find this in the document"* **without calling Gemini at all**. The AI is never
given junk to improvise from, so it can't make something up. (And no quota is used.)

### Step 6. Expand — add the paragraph next door

Chunking sometimes cuts an answer in half:

```
Piece 41: "...GPO launched govinfo, the successor to FDsys..."
                              ✂ cut here
Piece 42: "...The full-scale deployment was completed in FY 2018..."
```

For the top 3 pieces, expand also adds the piece **just before/after it in the same section**,
so Gemini gets both halves. Like reading the paragraph around a highlighted sentence.

It skips tables and chart descriptions (already complete), never crosses into another section,
skips pieces that are already selected, and stays within a size limit.

### Step 7. Gemini writes the answer

Gemini receives the question plus the 6 numbered pieces, each labelled with its section and page:

```
[1] TEXT | Section: Chapter 2 > South Asia > Outlook | p. 96
    Growth in SAR is expected to soften to 6.3 percent in 2026…
[2] TEXT | Section: Chapter 2 > South Asia > Outlook | pp. 96–97
    …
```

…and strict rules: use **only** these pieces · put `[n]` after every fact · copy numbers
exactly · don't mix regions · if the answer isn't there, say *"The document doesn't say."*

### Step 8. Cited answer

> Growth in South Asia is expected to soften to **6.3 percent in 2026** [1], then pick up to
> **7 percent per year in 2027–28** [2].

In the app, click `[1]` to see the exact piece, its section and page — so every fact can be checked.

---

## The whole thing in one table

| Step | In one line |
|---|---|
| **Parse** | Read the PDF with its layout: headings, tables, footnotes |
| **Detect** | Label it Narrative / Long & structured / Visual |
| **Vision** | Turn chart pages into text (short documents only) |
| **Chunk** | Cut into small labelled pieces — like building a book index |
| **Embed** | Give each piece a 384-number *meaning fingerprint* |
| **Store** | Save pieces, fingerprints and a word index in Postgres |
| **Scope** | Question names a section? Look only there |
| **Hybrid search** | Search by meaning **and** by exact words |
| **Fuse** | Merge the two result lists by position |
| **Rerank** | Read each shortlisted piece with the question; re-order by "does it answer?" |
| **Floor** | Nothing relevant → honest "not in the document", no AI call |
| **Expand** | Add the neighbouring paragraph so split answers arrive whole |
| **Gemini** | Write the answer from those pieces only, with `[n]` citations |

## Why the three documents need different handling

| Document | What makes it hard | Steps that solve it |
|---|---|---|
| **GPO** (narrative) | Nothing special — the baseline | Chunk + hybrid search + rerank is enough |
| **World Bank** (200 pages, structured) | Regions and chapters sound alike; tables are columns of numbers | **Headings → section paths**, **scope**, **tables rebuilt row by row** |
| **iMac** (visual) | Facts sit in charts, tables, call-outs and footnotes | **Vision for charts**, **tables rebuilt**, **footnotes attached** |

---

## Things worth playing with

Change a setting in `backend/.env`, restart the backend, and ask the same question again:

| Setting | Try this and watch what changes |
|---|---|
| `ENABLE_SECTION_SCOPE=false` | Ask the World Bank report about South Asia's risks — other regions' pieces creep in |
| `MIN_RERANK_SCORE=-11` | Ask something off-topic — the AI now gets junk pieces and may improvise |
| `RETRIEVE_K=1` or `12` | Fewer pieces = focused but may miss facts; more = fuller but noisier |
| `ENABLE_NEIGHBORS=false` | Answers split across two pieces get cut short |
| `CHUNK_CHARS=400` or `2500` | Smaller vs bigger pieces (re-upload needed — see below) |
| `ENABLE_VISION=false` | Re-upload the iMac report and ask about the carbon chart |
| `ENABLE_QUERY_REWRITE=false` | Saves one Gemini call on short follow-up questions |

To make a document process again after changing a chunking/vision setting, delete it first:
`psql -h localhost -U bacancy docrag -c "DELETE FROM documents WHERE id=1"` (then upload again).

**See the search without spending quota:** open any source in the app to see its reranker
score and its position in each search. Or use the command line (from `backend/`):

```bash
.venv/bin/python -m app.cli search 1 "South Asia growth"   # steps 1–6 only, no Gemini call
.venv/bin/python -m app.cli ask    1 "South Asia growth"   # full answer
.venv/bin/python -m app.cli parse  ../documents/GEP-Jun-2026.pdf --chunks   # see the pieces
```

---

## Where things live

```
documents/               the three exercise PDFs
backend/app/
  pipeline/parse.py      Parse — headings, tables, figures, footnotes
  pipeline/run.py        Detect + runs all preparation steps, reports progress
  pipeline/vision.py     Vision — chart pages to text
  pipeline/chunk.py      Chunk — cutting into pieces
  models.py              Embed + rerank (the two local models)
  db.py                  Store — Postgres tables
  retrieval.py           Scope, hybrid search, fuse, rerank, floor, expand
  rag.py                 The rules for Gemini + building the answer
  gemini.py              Calls to Gemini
  config.py              All settings, read from .env
  main.py                API routes the frontend calls
  cli.py                 Command-line tools
frontend/
  components/features/doc-chat/   the screens: upload, progress, chat, sources
  hooks/                          talking to the backend
```

## If something breaks

| Problem | Fix |
|---|---|
| Backend: "pgvector extension is not installed" | `sudo -u postgres psql -d docrag -c "CREATE EXTENSION vector;"` |
| Backend: connection refused | `sudo systemctl start postgresql` |
| "GEMINI_API_KEY is missing" | Put your key in `backend/.env` |
| Gemini 429 "quota exceeded" | The free tier allows only **~20 answers per day** for `gemini-3.6-flash`; wait for the reset shown in the message. Chart descriptions are saved, so re-uploading never spends quota again |
| Frontend: "Cannot reach the server" | Backend isn't running on port 8000 |
| "address already in use" on start | Something already runs on that port: `kill $(lsof -t -i:8000)` |
| Upload says "almost no text layer" | It's a scanned PDF — reading scans (OCR) is out of scope |
| Answers hang, but searching works | Broken IPv6 on the network; `gemini.py` already forces IPv4 |
| First question after a restart is slow (~1 min) | The two local models are loading; later questions take seconds |
