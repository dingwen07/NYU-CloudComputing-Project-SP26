"""Library browsing and IPNS discovery endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException

from common import db
from common.config import settings

router = APIRouter(tags=["library"])


def _entry_response(entry):
    return {
        "cid": entry.cid,
        "title": entry.title,
        "summary": entry.summary,
        "tags": entry.tags,
        "category": entry.category,
        "added_at": entry.added_at.isoformat(),
        "metadata_cid": entry.metadata_cid,
        "ipfs_url": f"{settings.IPFS_GATEWAY_URL}{entry.cid}",
    }


def _build_tag_index(entries):
    tag_index: dict[str, list[str]] = {}
    for entry in entries.values():
        for tag in entry.tags:
            cids = tag_index.setdefault(tag, [])
            if entry.cid not in cids:
                cids.append(entry.cid)
    return tag_index


@router.get("/library/tags")
async def get_library_tags():
    """Return all unique tags across library entries, sorted by frequency."""
    state = db.get_library_state()
    counts: dict[str, int] = {}
    for entry in state.entries.values():
        for tag in entry.tags:
            counts[tag] = counts.get(tag, 0) + 1
    return {
        "total_tags": len(counts),
        "tags": [
            {"tag": t, "count": c}
            for t, c in sorted(counts.items(), key=lambda x: -x[1])
        ],
    }


@router.get("/library/ipns")
async def get_library_ipns():
    """Discover the IPNS name for the knowledge library.

    This persistent IPNS name always resolves to the latest library index.
    Use it to find the library without knowing the current CID:
      ipfs name resolve <ipns_name>
      https://ipfs.io/ipns/<ipns_name>
    """
    ipns_name = db.get_ipns_name(settings.IPNS_LIBRARY_NAME)
    if not ipns_name:
        state = db.get_library_state()
        ipns_name = state.ipns_name

    if not ipns_name:
        raise HTTPException(404, "Library IPNS name not yet published. Submit and approve content first.")

    state = db.get_library_state()
    return {
        "ipns_name": ipns_name,
        "ipns_url": f"https://ipfs.io/ipns/{ipns_name}",
        "current_index_cid": state.index_cid,
        "resolve_command": f"ipfs name resolve {ipns_name}",
    }


@router.get("/library")
async def browse_library(tag: Optional[str] = None):
    """Browse the published knowledge library. Filter by tag with ?tag=<tag>."""
    state = db.get_library_state()
    entries = state.entries
    if tag:
        entries = {
            cid: entry
            for cid, entry in entries.items()
            if tag in entry.tags
        }
    tag_index = state.tag_index or _build_tag_index(state.entries)
    return {
        "version": state.version,
        "updated_at": state.updated_at.isoformat(),
        "index_cid": state.index_cid,
        "ipns_name": state.ipns_name,
        "total_entries": len(entries),
        "entries": {
            cid: _entry_response(entry)
            for cid, entry in entries.items()
        },
        "tag_index": tag_index,
    }


@router.get("/library/{cid}")
async def get_library_entry(cid: str):
    """Get a specific library entry by content CID."""
    state = db.get_library_state()
    entry = state.entries.get(cid)
    if entry:
        return _entry_response(entry)
    raise HTTPException(404, "Entry not found in library")
