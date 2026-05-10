import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))

from fastapi import FastAPI

from .processor import poll_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("llm-worker")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(poll_loop())
    logger.info("LLM Worker polling loop started")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("LLM Worker polling loop stopped")


app = FastAPI(
    title="IAN Knowledge Management - LLM Worker",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "llm-worker"}


@app.get("/status")
async def status():
    from common import db
    from common.enums import JobStatus

    processing = db.list_jobs(status=JobStatus.PROCESSING)
    processed = db.list_jobs(status=JobStatus.PROCESSED)
    return {
        "service": "llm-worker",
        "currently_processing": len(processing),
        "total_processed": len(processed),
    }
