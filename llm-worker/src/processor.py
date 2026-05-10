"""LLM Worker polling loop — processes content with Azure OpenAI."""

import asyncio
import io
import json
import logging

from openai import AzureOpenAI

from common.config import settings
from common import db
from common.enums import JobStatus
from common.ipfs import cat
from common.models import AiMetadata

from .prompts import SYSTEM_PROMPT, ANALYSIS_PROMPT

try:
    import pypdf
except ImportError:
    pypdf = None

logger = logging.getLogger("llm-worker.processor")


def _get_openai_client() -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=settings.AZURE_OPENAI_KEY,
        api_version=settings.AZURE_OPENAI_API_VERSION,
    )


async def poll_loop():
    """Main polling loop that picks up ASSIGNED jobs and processes them."""
    while True:
        try:
            await _tick()
        except Exception:
            logger.exception("Error in LLM worker poll tick")
        await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)


async def _tick():
    assigned = db.list_jobs(status=JobStatus.ASSIGNED)

    for job in assigned:
        logger.info(f"Processing job {job.id} (CID: {job.cid})")
        db.update_job(job.id, {"status": JobStatus.PROCESSING.value})

        try:
            ai_metadata = await _process_content(job.cid, title=job.title)
            updates = {
                "status": JobStatus.PROCESSED.value,
                "ai_metadata": ai_metadata,
            }
            if not job.title and ai_metadata.suggested_title:
                updates["title"] = ai_metadata.suggested_title
            db.update_job(job.id, updates)
            logger.info(f"Job {job.id} processed successfully")
        except Exception:
            logger.exception(f"Failed to process job {job.id}")
            db.update_job(job.id, {"status": JobStatus.FAILED.value})


def _extract_text(raw: bytes) -> str:
    """Extract text from raw bytes, handling PDF and plain text."""
    # Check for PDF magic bytes (%PDF-)
    if raw[:5] == b"%PDF-":
        if pypdf is None:
            raise RuntimeError("pypdf is required for PDF processing: pip install pypdf")
        reader = pypdf.PdfReader(io.BytesIO(raw))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)

    # Otherwise treat as UTF-8 text
    return raw.decode("utf-8", errors="replace")


async def _process_content(cid: str, *, title: str = "") -> AiMetadata:
    """Fetch content from IPFS by CID and analyze it with Azure OpenAI."""
    # Fetch content from IPFS
    raw = await cat(cid)
    content = _extract_text(raw)

    # Truncate very long content to fit in context window
    max_chars = 12000
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[... content truncated ...]"

    # Call Azure OpenAI
    client = _get_openai_client()
    response = client.chat.completions.create(
        model=settings.AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": ANALYSIS_PROMPT.format(
                    title=title or "(none provided)",
                    content=content,
                ),
            },
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    return AiMetadata(
        suggested_title=result.get("suggested_title", ""),
        summary=result.get("summary", ""),
        tags=result.get("tags", []),
        category=result.get("category", "other"),
        key_concepts=result.get("key_concepts", []),
    )
