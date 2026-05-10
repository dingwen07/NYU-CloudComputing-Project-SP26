"""Human-in-the-loop review endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel

from common import db
from common.enums import JobStatus
from common.models import AiMetadata

router = APIRouter(tags=["review"])

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


class ReviewAction(BaseModel):
    action: str  # "approve" or "reject"
    reviewer_notes: Optional[str] = None
    # Allow editing AI metadata before approval
    title: Optional[str] = None
    suggested_title: Optional[str] = None
    summary: Optional[str] = None
    tags: Optional[list[str]] = None
    category: Optional[str] = None


@router.get("/review/pending")
async def list_pending_reviews():
    """List all jobs pending human review."""
    jobs = db.list_jobs(status=JobStatus.PENDING_REVIEW)
    return [
        {
            "id": j.id,
            "cid": j.cid,
            "title": j.title,
            "status": j.status.value,
            "submitted_at": j.submitted_at.isoformat(),
            "ai_metadata": j.ai_metadata.model_dump() if j.ai_metadata else None,
        }
        for j in jobs
    ]


@router.get("/review/{job_id}", response_class=HTMLResponse)
async def review_page(request: Request, job_id: str):
    """Render the review page for a specific job."""
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return templates.TemplateResponse(
        request, "review_detail.html", {"job": job}
    )


@router.post("/review/{job_id}")
async def submit_review(job_id: str, review: ReviewAction):
    """Approve or reject a job after human review."""
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job.status != JobStatus.PENDING_REVIEW:
        raise HTTPException(400, f"Job is not pending review (status: {job.status})")

    updates: dict = {"reviewer_notes": review.reviewer_notes or ""}

    if review.action == "approve":
        approved_title = review.title or review.suggested_title
        if approved_title:
            updates["title"] = approved_title

        # Allow human to override AI metadata
        if job.ai_metadata and any([review.suggested_title, review.summary, review.tags, review.category]):
            updated_meta = AiMetadata(
                suggested_title=review.suggested_title or job.ai_metadata.suggested_title,
                summary=review.summary or job.ai_metadata.summary,
                tags=review.tags if review.tags is not None else job.ai_metadata.tags,
                category=review.category or job.ai_metadata.category,
                key_concepts=job.ai_metadata.key_concepts,
            )
            updates["ai_metadata"] = updated_meta
        updates["status"] = JobStatus.APPROVED.value
    elif review.action == "reject":
        updates["status"] = JobStatus.REJECTED.value
    else:
        raise HTTPException(400, f"Invalid action: {review.action}")

    db.update_job(job_id, updates)
    return {"id": job_id, "status": updates["status"]}
