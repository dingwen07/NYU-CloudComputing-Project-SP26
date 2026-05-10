import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))

from fastapi import FastAPI

from common import p2p

from .worker import poll_loop, run_tick

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")


@asynccontextmanager
async def lifespan(app: FastAPI):
    p2p.start_node(
        "orchestrator",
        {
            "job.submitted": lambda event: run_tick(),
            "job.processed": lambda event: run_tick(),
        },
    )
    task = asyncio.create_task(poll_loop())
    logger.info("Orchestrator polling loop and libp2p node started")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    p2p.stop_node()
    logger.info("Orchestrator polling loop stopped")


app = FastAPI(
    title="IAN Knowledge Management - Orchestrator",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "orchestrator", "p2p": p2p.status()}


@app.get("/status")
async def status():
    from common import db

    jobs = db.list_jobs(limit=200)
    counts = {}
    for j in jobs:
        counts[j.status.value] = counts.get(j.status.value, 0) + 1
    return {"service": "orchestrator", "job_counts": counts}
