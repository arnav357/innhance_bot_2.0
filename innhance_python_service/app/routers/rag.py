"""RAG router — document ingestion and chunk retrieval."""
from fastapi import APIRouter, BackgroundTasks
from app.models.schemas import (
    IngestRequest, IngestResponse, IngestStatusResponse,
    RetrieveRequest, RetrieveResponse,
)
from app.services.rag import ingest_document, retrieve_chunks
from app.core.database import get_supabase

router = APIRouter(tags=["rag"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest, background_tasks: BackgroundTasks):
    """
    Start document ingestion as a background task.
    Returns immediately with status=queued.
    Poll GET /ingest/status for completion.
    """
    background_tasks.add_task(ingest_document, req)
    return IngestResponse(
        status="queued",
        venue_id=req.venue_id,
        source_name=req.source_name,
    )


@router.get("/ingest/status", response_model=IngestStatusResponse)
async def ingest_status(venue_id: str, source_name: str):
    """Poll ingestion status for a specific document."""
    db = get_supabase()
    result = (
        db.table("knowledge_sources")
        .select("*")
        .eq("venue_id", venue_id)
        .eq("source_name", source_name)
        .maybe_single()
        .execute()
    )
    if not result.data:
        return IngestStatusResponse(
            venue_id=venue_id,
            source_name=source_name,
            status="processing",
        )
    row = result.data
    return IngestStatusResponse(
        venue_id=venue_id,
        source_name=source_name,
        status=row.get("status", "processing"),
        chunk_count=row.get("chunk_count"),
        error=row.get("error"),
    )


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(req: RetrieveRequest):
    """
    Retrieve top-K relevant chunks for a guest query.
    Strictly filtered by venue_id — no cross-venue data leakage possible.
    """
    return await retrieve_chunks(req)
