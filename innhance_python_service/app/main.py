"""
Innhance AI Service — main application entry point.

Start locally:
    uvicorn app.main:app --reload --port 8000

Production (Railway):
    uvicorn app.main:app --host 0.0.0.0 --port $APP_PORT --workers 2
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers import health, language, classify, rag, payment, reply

settings = get_settings()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ── Startup / shutdown ────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("innhance-ai starting | env=%s", settings.app_env)
    yield
    logger.info("innhance-ai shutting down")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Innhance AI Service",
    description="FastAPI service providing intent classification, RAG retrieval, language detection, and payment verification for the Innhance hotel bot.",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url=None,
)

# CORS — only allow the Node.js bot server and dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "development" else [
        "https://innhance-bot.railway.app",
        "https://innhance.vercel.app",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


# ── Global error handler ──────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(language.router)
app.include_router(classify.router)
app.include_router(rag.router)
app.include_router(payment.router)
app.include_router(reply.router)

logger.info("routes registered: /health /detect-language /classify /ingest /retrieve /verify-payment /reply")
