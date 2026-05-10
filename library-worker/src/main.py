import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))

from fastapi import FastAPI

from .publisher import poll_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("library-worker")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(poll_loop())
    logger.info("Library Worker polling loop started")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Library Worker polling loop stopped")


app = FastAPI(
    title="IAN Knowledge Management - Library Worker",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "library-worker"}


@app.get("/status")
async def status():
    from common import db

    state = db.get_library_state()
    return {
        "service": "library-worker",
        "library_version": state.version,
        "total_entries": len(state.entries),
        "total_tags": len(state.tag_index),
        "index_cid": state.index_cid,
        "ipns_name": state.ipns_name,
    }
