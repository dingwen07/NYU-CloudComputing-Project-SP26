"""Job submission and listing endpoints."""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from common import db
from common.enums import JobStatus
from common.models import Job

router = APIRouter(tags=["jobs"])


class JobSubmission(BaseModel):
    cid: str
    title: str = ""
    user_metadata: dict = {}


class JobResponse(BaseModel):
    id: str
    cid: str
    title: str
    status: str
    submitted_by: str
    submitted_at: str
    updated_at: str
    user_metadata: dict
    ai_metadata: Optional[dict] = None
    reviewer_notes: Optional[str] = None
    published_cid: Optional[str] = None


def _job_to_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        cid=job.cid,
        title=job.title,
        status=job.status.value,
        submitted_by=job.submitted_by,
        submitted_at=job.submitted_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        user_metadata=job.user_metadata,
        ai_metadata=job.ai_metadata.model_dump() if job.ai_metadata else None,
        reviewer_notes=job.reviewer_notes,
        published_cid=job.published_cid,
    )


@router.post("/jobs", status_code=201)
async def submit_job(submission: JobSubmission):
    """Submit a new CID for knowledge processing."""
    job = Job(
        id=str(uuid.uuid4()),
        cid=submission.cid,
        title=submission.title,
        user_metadata=submission.user_metadata,
    )
    db.create_job(job)
    return _job_to_response(job)


@router.get("/jobs")
async def get_jobs(status: Optional[str] = None, limit: int = 50):
    """List jobs, optionally filtered by status."""
    job_status = None
    if status:
        try:
            job_status = JobStatus(status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")

    jobs = db.list_jobs(status=job_status, limit=limit)
    return [_job_to_response(j) for j in jobs]


@router.get("/jobs/{job_id}")
async def get_job_detail(job_id: str):
    """Get details of a specific job."""
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_to_response(job)
