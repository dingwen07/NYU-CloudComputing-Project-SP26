"""Firestore client wrapper for job and library state management."""

import base64
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore

from .config import settings
from .enums import JobStatus
from .models import AiMetadata, Job, LibraryEntry, LibraryIndex

_client: Optional[firestore.Client] = None

JOBS_COLLECTION = "jobs"
LIBRARY_COLLECTION = "library"
LIBRARY_STATE_DOC = "library/state"


def get_db() -> firestore.Client:
    global _client
    if _client is None:
        _client = firestore.Client(project=settings.GCP_PROJECT_ID)
    return _client


def _job_from_doc(doc: firestore.DocumentSnapshot) -> Job:
    data = doc.to_dict()
    if data.get("ai_metadata") and isinstance(data["ai_metadata"], dict):
        data["ai_metadata"] = AiMetadata(**data["ai_metadata"])
    return Job(id=doc.id, **{k: v for k, v in data.items() if k != "id"})


# --- Job operations ---


def create_job(job: Job) -> str:
    db = get_db()
    doc_ref = db.collection(JOBS_COLLECTION).document(job.id)
    doc_data = job.model_dump(exclude={"id"})
    doc_data["ai_metadata"] = (
        job.ai_metadata.model_dump() if job.ai_metadata else None
    )
    doc_ref.set(doc_data)
    return job.id


def get_job(job_id: str) -> Optional[Job]:
    db = get_db()
    doc = db.collection(JOBS_COLLECTION).document(job_id).get()
    if not doc.exists:
        return None
    return _job_from_doc(doc)


def list_jobs(status: Optional[JobStatus] = None, limit: int = 100) -> list[Job]:
    db = get_db()
    query = db.collection(JOBS_COLLECTION)
    if status:
        query = query.where(filter=firestore.FieldFilter("status", "==", status.value))
    query = query.order_by("submitted_at", direction=firestore.Query.DESCENDING)
    query = query.limit(limit)
    return [_job_from_doc(doc) for doc in query.stream()]


def update_job(job_id: str, updates: dict) -> None:
    db = get_db()
    updates["updated_at"] = datetime.now(timezone.utc)
    if "ai_metadata" in updates and isinstance(updates["ai_metadata"], AiMetadata):
        updates["ai_metadata"] = updates["ai_metadata"].model_dump()
    db.collection(JOBS_COLLECTION).document(job_id).update(updates)


# --- Library state operations ---


def get_library_state() -> LibraryIndex:
    db = get_db()
    doc = db.document(LIBRARY_STATE_DOC).get()
    if not doc.exists:
        return LibraryIndex()
    data = doc.to_dict()
    raw_entries = data.get("entries", {})
    if isinstance(raw_entries, list):
        entries = {
            e["cid"]: LibraryEntry(**e)
            for e in raw_entries
            if isinstance(e, dict) and e.get("cid")
        }
    else:
        entries = {
            cid: LibraryEntry(**entry)
            for cid, entry in raw_entries.items()
        }
    return LibraryIndex(
        version=data.get("version", 1),
        updated_at=data.get("updated_at", datetime.now(timezone.utc)),
        entries=entries,
        tag_index=data.get("tag_index", {}),
        ipns_name=data.get("ipns_name", ""),
        index_cid=data.get("index_cid", ""),
    )


def update_library_state(index: LibraryIndex) -> None:
    db = get_db()
    data = index.model_dump()
    data["entries"] = {
        cid: entry.model_dump()
        for cid, entry in index.entries.items()
    }
    db.document(LIBRARY_STATE_DOC).set(data)


# --- IPNS key persistence ---

KEYS_COLLECTION = "ipns_keys"


def get_ipns_key(key_name: str) -> Optional[bytes]:
    """Retrieve a stored IPNS key (raw bytes) from Firestore."""
    db = get_db()
    doc = db.collection(KEYS_COLLECTION).document(key_name).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    return base64.b64decode(data["key_data"])


def store_ipns_key(key_name: str, key_bytes: bytes, peer_id: str) -> None:
    """Store an exported IPNS key in Firestore for persistence across restarts."""
    db = get_db()
    db.collection(KEYS_COLLECTION).document(key_name).set({
        "key_data": base64.b64encode(key_bytes).decode(),
        "peer_id": peer_id,
        "updated_at": datetime.now(timezone.utc),
    })


def get_ipns_name(key_name: str) -> Optional[str]:
    """Get the IPNS name (peer ID) for a stored key without retrieving the key itself."""
    db = get_db()
    doc = db.collection(KEYS_COLLECTION).document(key_name).get()
    if not doc.exists:
        return None
    return doc.to_dict().get("peer_id")
