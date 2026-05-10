"""Orchestrator polling loop — manages job lifecycle transitions."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from common.config import settings
from common import db
from common.enums import JobStatus
from common import p2p

logger = logging.getLogger("orchestrator.worker")

# Jobs older than this without being processed are cancelled (content unavailable)
JOB_TIMEOUT = timedelta(minutes=30)
_tick_lock = asyncio.Lock()


async def poll_loop():
    """Main polling loop that drives job state transitions."""
    while True:
        try:
            await run_tick()
        except Exception:
            logger.exception("Error in orchestrator poll tick")
        await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)


async def run_tick():
    async with _tick_lock:
        await _tick()


async def _tick():
    # 1. Move SUBMITTED → ASSIGNED (ready for LLM processing)
    submitted = db.list_jobs(status=JobStatus.SUBMITTED)
    for job in submitted:
        # Check for timeout — if content was never available, cancel
        age = datetime.now(timezone.utc) - job.submitted_at
        if age > JOB_TIMEOUT:
            logger.info(f"Job {job.id} timed out (submitted {age} ago), cancelling")
            db.update_job(job.id, {"status": JobStatus.CANCELLED.value})
            continue

        logger.info(f"Assigning job {job.id}")
        db.update_job(job.id, {"status": JobStatus.ASSIGNED.value})
        p2p.publish("job.assigned", job_id=job.id, cid=job.cid)

    # 2. Move PROCESSED → PENDING_REVIEW (ready for human review)
    processed = db.list_jobs(status=JobStatus.PROCESSED)
    for job in processed:
        logger.info(f"Job {job.id} ready for review")
        db.update_job(job.id, {"status": JobStatus.PENDING_REVIEW.value})
        p2p.publish("job.pending_review", job_id=job.id, cid=job.cid)

    # 3. Check for stale ASSIGNED/PROCESSING jobs (timeout handling)
    assigned = db.list_jobs(status=JobStatus.ASSIGNED)
    for job in assigned:
        age = datetime.now(timezone.utc) - job.updated_at
        if age > JOB_TIMEOUT:
            logger.warning(f"Job {job.id} stuck in ASSIGNED for {age}, cancelling")
            db.update_job(job.id, {"status": JobStatus.CANCELLED.value})

    processing = db.list_jobs(status=JobStatus.PROCESSING)
    for job in processing:
        age = datetime.now(timezone.utc) - job.updated_at
        if age > JOB_TIMEOUT:
            logger.warning(f"Job {job.id} stuck in PROCESSING for {age}, cancelling")
            db.update_job(job.id, {"status": JobStatus.CANCELLED.value})
