"""
HTTP API.

  POST /api/documents           upload a PDF -> starts the pipeline (or reuses
                                the processed copy if this exact file was seen)
  GET  /api/documents/{id}      status, live stage progress, detected profile
  POST /api/chat                {documentId, message, history} -> cited answer
  POST /api/search              {documentId, query} -> retrieval only, no AI call
  GET  /api/health
"""

import hashlib
import threading

import pymupdf
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import config, db, gemini, models
from .pipeline.run import run_pipeline
from .rag import answer
from .retrieval import retrieve

app = FastAPI(title="Doc RAG")
app.add_middleware(CORSMiddleware, allow_origins=[config.CORS_ORIGIN], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def startup():
    db.init_db()
    config.UPLOAD_DIR.mkdir(exist_ok=True)
    # A restart mid-ingest leaves a document stuck in 'processing' forever.
    db.execute(
        "UPDATE documents SET status='failed', error='Processing was interrupted by a server restart. Upload again to retry.' "
        "WHERE status='processing'"
    )
    # Load the local models in the background so the first question is fast.
    threading.Thread(target=lambda: (models.embedder(), models.reranker()), daemon=True).start()


def _doc(doc_id: int) -> dict:
    row = db.fetch_one("SELECT * FROM documents WHERE id=%s", (doc_id,))
    if not row:
        raise HTTPException(404, "Document not found")
    return row


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "geminiKey": bool(config.GEMINI_API_KEY and config.GEMINI_API_KEY != "paste_your_key_here"),
        "chatModel": config.CHAT_MODEL,
        "embedModel": config.EMBED_MODEL,
        "rerankModel": config.RERANK_MODEL,
    }


@app.post("/api/documents")
async def upload(background: BackgroundTasks, file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {config.MAX_UPLOAD_MB} MB")
    try:
        pdf = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise HTTPException(400, "That file is not a readable PDF")
    if len(pdf) > config.MAX_PAGES:
        raise HTTPException(400, f"PDF has {len(pdf)} pages; the limit is {config.MAX_PAGES}")
    if sum(len(p.get_text()) for p in pdf) < 50 * len(pdf):
        raise HTTPException(400, "This PDF has almost no text layer (a scan?). OCR is out of scope for this project.")

    sha = hashlib.sha256(data).hexdigest()
    existing = db.fetch_one("SELECT id, status FROM documents WHERE sha256=%s", (sha,))
    if existing and existing["status"] in ("ready", "processing"):
        return {"id": existing["id"], "reused": existing["status"] == "ready"}

    path = config.UPLOAD_DIR / f"{sha}.pdf"
    path.write_bytes(data)
    if existing:  # failed before -> run again
        doc_id = existing["id"]
        db.execute(
            "UPDATE documents SET status='processing', error=NULL, stage=NULL, progress='{}', updated_at=now() WHERE id=%s",
            (doc_id,),
        )
    else:
        doc_id = db.fetch_one(
            "INSERT INTO documents (sha256, filename, pages) VALUES (%s,%s,%s) RETURNING id",
            (sha, file.filename or "document.pdf", len(pdf)),
        )["id"]
    background.add_task(run_pipeline, doc_id, str(path), sha)
    return {"id": doc_id, "reused": False}


@app.get("/api/documents/{doc_id}")
def document(doc_id: int):
    d = _doc(doc_id)
    return {
        "id": d["id"],
        "filename": d["filename"],
        "title": d["title"],
        "pages": d["pages"],
        "status": d["status"],
        "stage": d["stage"],
        "progress": d["progress"],
        "profile": d["profile"],
        "error": d["error"],
    }


class ChatIn(BaseModel):
    documentId: int
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict] = []


@app.post("/api/chat")
def chat(body: ChatIn):
    d = _doc(body.documentId)
    if d["status"] != "ready":
        raise HTTPException(409, "This document is not processed yet")
    history = [
        {"role": "model" if m.get("role") in ("assistant", "model") else "user", "text": str(m.get("text", ""))}
        for m in body.history
        if m.get("text")
    ]
    try:
        return answer(d, body.message.strip(), history)
    except gemini.GeminiError as e:
        raise HTTPException(502, str(e))


class SearchIn(BaseModel):
    documentId: int
    query: str = Field(min_length=1, max_length=2000)


@app.post("/api/search")
def search(body: SearchIn):
    _doc(body.documentId)
    return retrieve(body.documentId, body.query)
