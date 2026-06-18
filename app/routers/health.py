"""Health check router."""
from fastapi import APIRouter
import time

router = APIRouter()
_start = time.time()

@router.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "innhance-ai",
        "uptime_seconds": round(time.time() - _start),
    }
