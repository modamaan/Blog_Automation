from __future__ import annotations

import logging
import uuid
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.connection import engine, Base
from app.config import settings  # validates env at startup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — creating DB tables if needed")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("DB ready. LangGraph pipeline API is live.")
    
    yield
    
    logger.info("Shutting down pipeline API")


app = FastAPI(
    title="DevBlog Pipeline API",
    description="LangGraph-powered autonomous blog content pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "devblog_url": settings.devblog_base_url,
    }


# ─── Routers (imported after app creation to avoid circular imports) ──────────
from app.routers import pipeline, telegram  # noqa: E402

app.include_router(pipeline.router, prefix="/pipeline", tags=["pipeline"])
app.include_router(telegram.router, prefix="/telegram", tags=["telegram"])
