import sys
import logging
from pathlib import Path

# Add common package to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .routers import jobs, review, library

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api-server")


app = FastAPI(
    title="IAN Knowledge Management - API Server",
    version="0.1.0",
)

templates_dir = Path(__file__).parent / "templates"
static_dir = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(templates_dir))
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(jobs.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(library.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "api-server"}


@app.get("/")
async def dashboard(request: Request):
    from common import db
    from common.enums import JobStatus

    all_jobs = db.list_jobs(limit=50)
    pending_review = [j for j in all_jobs if j.status == JobStatus.PENDING_REVIEW]
    published = [j for j in all_jobs if j.status == JobStatus.PUBLISHED]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "total_jobs": len(all_jobs),
            "pending_review": len(pending_review),
            "published": len(published),
            "recent_jobs": all_jobs[:10],
        },
    )


@app.get("/library")
async def library_page(request: Request):
    return templates.TemplateResponse(request, "library.html", {})


@app.get("/review")
async def review_queue_page(request: Request):
    return templates.TemplateResponse(request, "review.html", {})
