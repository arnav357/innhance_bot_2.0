"""
RAG service — document ingestion and chunk retrieval.

Ingestion flow:
  PDF/URL → extract text → chunk → embed → store in pgvector (Supabase)

Retrieval flow:
  query → embed → cosine similarity search (WHERE venue_id = X) → top-K chunks

All queries are strictly filtered by venue_id. Cross-venue data leakage
is impossible at the query level and enforced again by Supabase RLS.
"""

import re
import base64
import logging
import hashlib
from typing import Optional
import httpx
from bs4 import BeautifulSoup

from app.core import llm
from app.core.config import get_settings
from app.core.database import get_supabase
from app.models.schemas import (
    IngestRequest, IngestResponse,
    RetrieveRequest, RetrieveResponse, Chunk,
)

logger   = logging.getLogger(__name__)
settings = get_settings()


# ── Text extraction ────────────────────────────────────────────────────────────

def _extract_pdf_text(base64_data: str) -> str:
    """Extract plain text from a base64-encoded PDF using pymupdf."""
    import fitz  # pymupdf
    pdf_bytes = base64.b64decode(base64_data)
    doc  = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = "\n\n".join(page.get_text("text") for page in doc)
    doc.close()
    return text.strip()


async def _extract_url_text(url: str) -> str:
    """
    Fetch a URL and extract readable text content.
    Handles both static HTML and JS-heavy sites (extracts whatever is available).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Innhance-Bot/2.0)",
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract meta description — useful even on JS sites
    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if meta_tag and meta_tag.get("content"):
        meta_desc = meta_tag["content"].strip()

    # Extract Open Graph data
    og_texts = []
    for prop in ["og:title", "og:description", "og:site_name"]:
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            og_texts.append(tag["content"].strip())

    # Remove non-content tags
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "noscript", "iframe", "svg", "path"]):
        tag.decompose()

    body_text = soup.get_text(separator="\n")
    # Collapse horizontal whitespace but PRESERVE newlines for chunking
    body_text = re.sub(r"[ \t]{2,}", " ", body_text)
    body_text = re.sub(r"\n{4,}", "\n\n\n", body_text)
    body_text = body_text.strip()

    # Combine all extracted content
    all_parts = []
    if og_texts:
        all_parts.append(" | ".join(og_texts))
    if meta_desc:
        all_parts.append(meta_desc)
    if body_text and len(body_text) > 50:
        all_parts.append(body_text)

    combined = "\n\n".join(all_parts)

    if len(combined.strip()) < 100:
        raise ValueError(
            f"Could not extract meaningful text from {url}. "
            "The site may be JavaScript-rendered. "
            "Please upload a PDF or use the manual FAQ option instead."
        )

    return combined


# ── Chunking ───────────────────────────────────────────────────────────────────

def _split_into_chunks(
    text: str,
    source_type: str,
    chunk_size: int = None,
    chunk_overlap: int = None,
) -> list[str]:
    """
    Split text into chunks appropriate for the source type.

    FAQs: split on Q&A boundaries (one chunk per Q+A pair)
    Everything else: token-approximate sliding window with overlap
    """
    chunk_size    = chunk_size    or settings.chunk_size
    chunk_overlap = chunk_overlap or settings.chunk_overlap

    if source_type == "faq":
        return _split_faq(text)
    return _sliding_window_chunks(text, chunk_size, chunk_overlap)


def _split_faq(text: str) -> list[str]:
    """
    Split FAQ text into individual Q&A pairs.
    Expects format: Q: ... / A: ... or numbered questions.
    Falls back to paragraph splitting if no Q/A markers found.
    """
    # Try Q: / A: format
    qa_pattern = re.findall(r"(Q[\.\:\s].+?)(?=Q[\.\:\s]|\Z)", text, re.DOTALL | re.IGNORECASE)
    if qa_pattern and len(qa_pattern) > 1:
        return [chunk.strip() for chunk in qa_pattern if len(chunk.strip()) > 20]

    # Try numbered questions
    numbered = re.split(r"\n\s*\d+[\.\)]\s+", text)
    if len(numbered) > 2:
        return [chunk.strip() for chunk in numbered if len(chunk.strip()) > 20]

    # Fallback: paragraph split
    return [p.strip() for p in text.split("\n\n") if len(p.strip()) > 30]


def _sliding_window_chunks(text: str, chunk_size: int, overlap: int) -> list[str]:
    """
    Chunk text using a sliding window approach.
    First splits on paragraph boundaries, then applies word-count window
    so very long paragraphs still get split, and short ones get merged.
    """
    approx_chunk_words   = int(chunk_size / 1.3)
    approx_overlap_words = int(overlap / 1.3)

    # Split into paragraphs first
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if len(p.strip()) > 20]

    # Merge short paragraphs into groups up to chunk_size, then split oversized ones
    chunks = []
    current_words = []

    for para in paragraphs:
        para_words = para.split()
        # If adding this paragraph would exceed chunk size, flush current buffer
        if current_words and len(current_words) + len(para_words) > approx_chunk_words:
            chunks.append(" ".join(current_words))
            # Keep overlap words for context continuity
            current_words = current_words[-approx_overlap_words:] if approx_overlap_words else []
        current_words.extend(para_words)

        # If current buffer is already over chunk size, flush it
        while len(current_words) > approx_chunk_words:
            chunks.append(" ".join(current_words[:approx_chunk_words]))
            current_words = current_words[approx_chunk_words - approx_overlap_words:]

    # Flush remaining
    if current_words and len(" ".join(current_words)) > 30:
        chunks.append(" ".join(current_words))

    return chunks


# ── Storage ───────────────────────────────────────────────────────────────────

def _source_id(venue_id: str, source_name: str) -> str:
    """Deterministic source ID used to delete + replace chunks on re-ingest."""
    return hashlib.sha256(f"{venue_id}::{source_name}".encode()).hexdigest()[:16]


async def _store_chunks(
    venue_id: str,
    source_type: str,
    source_id: str,
    language: str,
    chunks: list[str],
    image_url: Optional[str] = None,
) -> int:
    """Embed all chunks and upsert into Supabase pgvector."""
    if not chunks:
        return 0

    db = get_supabase()

    # Delete existing chunks for this source (atomic swap on re-ingest)
    db.table("chunks").delete().eq("venue_id", venue_id).eq("source_id", source_id).execute()

    # Embed in batches of 50 (OpenAI embedding API limit per request is 2048)
    batch_size   = 50
    stored_count = 0

    for i in range(0, len(chunks), batch_size):
        batch      = chunks[i : i + batch_size]
        embeddings = await llm.embed(batch)

        rows = [
            {
                "venue_id":    venue_id,
                "source_type": source_type,
                "source_id":   source_id,
                "language":    language,
                "text":        chunk,
                "embedding":   embedding,
                "image_url":   image_url,
            }
            for chunk, embedding in zip(batch, embeddings)
        ]
        db.table("chunks").insert(rows).execute()
        stored_count += len(rows)
        logger.info("stored %d/%d chunks for venue=%s", stored_count, len(chunks), venue_id)

    return stored_count


# ── Public: ingest ─────────────────────────────────────────────────────────────

async def ingest_document(req: IngestRequest) -> IngestResponse:
    """
    Extract → chunk → embed → store.
    Called as a FastAPI BackgroundTask — never blocks the HTTP response.
    """
    sid = _source_id(req.venue_id, req.source_name)

    # Update status to processing
    db = get_supabase()
    db.table("knowledge_sources").upsert({
        "venue_id":    req.venue_id,
        "source_id":   sid,
        "source_name": req.source_name,
        "source_type": req.source_type,
        "status":      "processing",
    }).execute()

    try:
        # Extract text
        if req.file_base64:
            text = _extract_pdf_text(req.file_base64)
        else:
            text = await _extract_url_text(req.url)

        if not text or len(text.strip()) < 50:
            raise ValueError("Extracted text is too short — document may be empty or image-only PDF")

        # Chunk
        chunks = _split_into_chunks(text, req.source_type)
        logger.info("ingesting venue=%s source=%s → %d chunks", req.venue_id, req.source_name, len(chunks))

        # Embed + store
        count = await _store_chunks(
            venue_id=req.venue_id,
            source_type=req.source_type,
            source_id=sid,
            language=req.language,
            chunks=chunks,
        )

        db.table("knowledge_sources").update({
            "status":      "ready",
            "chunk_count": count,
        }).eq("venue_id", req.venue_id).eq("source_id", sid).execute()

        logger.info("ingest complete: venue=%s source=%s chunks=%d", req.venue_id, req.source_name, count)

    except Exception as exc:
        logger.error("ingest failed: venue=%s source=%s error=%s", req.venue_id, req.source_name, exc)
        db.table("knowledge_sources").update({
            "status": "failed",
            "error":  str(exc),
        }).eq("venue_id", req.venue_id).eq("source_id", sid).execute()

    return IngestResponse(
        status="queued",
        venue_id=req.venue_id,
        source_name=req.source_name,
    )


# ── Public: retrieve ───────────────────────────────────────────────────────────

async def retrieve_chunks(req: RetrieveRequest) -> RetrieveResponse:
    """
    Embed the query and run cosine similarity search against stored chunks.
    Strictly filtered by venue_id — cross-venue retrieval is impossible.
    """
    query_embedding = (await llm.embed([req.query]))[0]

    db = get_supabase()

    # pgvector cosine similarity search via Supabase RPC
    # The SQL function `match_chunks` must be created in Supabase (see supabase/migrations/)
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    result = db.rpc("match_chunks", {
        "query_embedding": embedding_str,
        "match_venue_id":  req.venue_id,
        "match_count":     req.top_k,
        "min_similarity":  settings.rag_min_similarity,
    }).execute()

    rows = result.data or []

    if not rows:
        logger.info("retrieve: no chunks above threshold | venue=%s query=%r", req.venue_id, req.query[:60])
        return RetrieveResponse(
            chunks=[],
            venue_id=req.venue_id,
            retrieved=0,
            below_threshold=True,
        )

    chunks = [
        Chunk(
            text=row["text"],
            similarity=row["similarity"],
            source_type=row["source_type"],
            image_url=row.get("image_url"),
        )
        for row in rows
    ]

    logger.info(
        "retrieve: %d chunks | venue=%s top_sim=%.3f",
        len(chunks), req.venue_id, chunks[0].similarity,
    )

    return RetrieveResponse(
        chunks=chunks,
        venue_id=req.venue_id,
        retrieved=len(chunks),
        below_threshold=False,
    )