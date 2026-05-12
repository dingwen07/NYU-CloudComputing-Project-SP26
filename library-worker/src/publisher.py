"""Library Worker polling loop — publishes approved content to IPFS/IPNS."""

import asyncio
import logging
from datetime import datetime, timezone

from common.config import settings
from common import db
from common.enums import JobStatus
from common.ipfs import add_json, publish_ipns, resolve_ipns
from common.models import LibraryEntry
from common import p2p

logger = logging.getLogger("library-worker.publisher")
_last_republish_utc: float = 0
_REPUBLISH_INTERVAL_SECONDS = 4 * 3600  # re-announce IPNS every 4 hours
_tick_lock = asyncio.Lock()


async def poll_loop():
    """Main polling loop that picks up APPROVED jobs and publishes them."""
    while True:
        try:
            await run_tick()
        except Exception:
            logger.exception("Error in library worker poll tick")
        await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)


async def run_tick():
    async with _tick_lock:
        await _tick()


async def _tick():
    global _last_republish_utc

    approved = db.list_jobs(status=JobStatus.APPROVED)

    if not approved:
        now = datetime.now(timezone.utc).timestamp()
        if now - _last_republish_utc >= _REPUBLISH_INTERVAL_SECONDS:
            await _republish_existing_index()
            _last_republish_utc = now
        return

    # Get current library state
    library = db.get_library_state()
    changed = False
    published_jobs = []

    for job in approved:
        logger.info(f"Publishing job {job.id} to library")

        try:
            # Create library entry metadata
            title = (
                job.ai_metadata.suggested_title
                if job.ai_metadata and job.ai_metadata.suggested_title
                else job.title or f"Document {job.cid[:12]}"
            )
            entry_data = {
                "cid": job.cid,
                "title": title,
                "summary": job.ai_metadata.summary if job.ai_metadata else "",
                "tags": job.ai_metadata.tags if job.ai_metadata else [],
                "category": job.ai_metadata.category if job.ai_metadata else "other",
                "added_at": datetime.now(timezone.utc).isoformat(),
                "job_id": job.id,
            }

            # Pin the entry metadata to IPFS (retry up to 3 times)
            metadata_cid = None
            for attempt in range(3):
                try:
                    metadata_cid = await add_json(entry_data, name=f"entry-{job.id}.json")
                    break
                except Exception:
                    if attempt < 2:
                        logger.warning(f"IPFS add failed (attempt {attempt + 1}/3), retrying in 5s...")
                        await asyncio.sleep(5)
                    else:
                        raise
            logger.info(f"Entry metadata pinned: {metadata_cid}")

            # Add to library index
            entry = LibraryEntry(
                cid=job.cid,
                title=entry_data["title"],
                summary=entry_data["summary"],
                tags=entry_data["tags"],
                category=entry_data["category"],
                metadata_cid=metadata_cid,
            )
            library.entries[job.cid] = entry
            changed = True
            published_jobs.append((job.id, metadata_cid))

        except Exception:
            logger.exception(f"Failed to publish job {job.id}")
            db.update_job(job.id, {"status": JobStatus.FAILED.value})

    if changed:
        # Generate library -> upload/pin to IPFS -> get CID -> publish CID to IPNS
        library.version += 1
        library.updated_at = datetime.now(timezone.utc)
        await _publish_library_index_to_ipns(library)

        # Persist Firestore only after IPFS and IPNS both point at the new library.
        db.update_library_state(library)

        for job_id, metadata_cid in published_jobs:
            db.update_job(
                job_id,
                {
                    "status": JobStatus.PUBLISHED.value,
                    "published_cid": metadata_cid,
                },
            )
            p2p.publish("job.published", job_id=job_id, metadata_cid=metadata_cid)
            logger.info(f"Job {job_id} published successfully")


async def _republish_existing_index():
    """Re-publish the library index to IPNS so DHT records don't expire."""
    library = db.get_library_state()
    if not library.entries:
        return

    try:
        await _publish_library_index_to_ipns(library)
        db.update_library_state(library)
        logger.info("Republished library index to IPNS: %s", library.index_cid)
    except Exception:
        logger.exception("Failed to republish library index to IPNS")


async def _publish_library_index_to_ipns(library):
    """Publish the library payload, then publish the resulting CID to IPNS."""
    payload = _build_library_index_payload(library)
    index_cid = await add_json(
        payload,
        name="library-index.json",
    )
    logger.info(f"Library index pinned: v{library.version}, CID: {index_cid}")

    ipns_name = await publish_ipns(index_cid, key=settings.IPNS_LIBRARY_NAME)
    logger.info(f"IPNS updated: {ipns_name} -> {index_cid}")

    try:
        resolved_cid = await resolve_ipns(ipns_name)
        if resolved_cid != index_cid:
            logger.warning(
                "IPNS resolve returned stale record: %s resolved to %s, expected %s "
                "(DHT propagation may be slow)",
                ipns_name, resolved_cid, index_cid,
            )
    except Exception:
        logger.warning("IPNS resolve check failed (DHT may still be propagating)", exc_info=True)

    library.tag_index = payload["tag_index"]
    library.index_cid = index_cid
    library.ipns_name = ipns_name


def _build_library_index_payload(library):
    """Build the IPFS library JSON payload.

    This payload intentionally excludes index_cid and ipns_name because the CID
    is assigned by IPFS after hashing these bytes.
    """
    # Build tag → [cid, ...] reverse index
    tag_index: dict[str, list[str]] = {}
    for e in library.entries.values():
        for tag in e.tags:
            cids = tag_index.setdefault(tag, [])
            if e.cid not in cids:
                cids.append(e.cid)

    return {
        "version": library.version,
        "updated_at": library.updated_at.isoformat(),
        "entries": {
            cid: entry.model_dump(mode="json")
            for cid, entry in library.entries.items()
        },
        "tag_index": tag_index,
    }
