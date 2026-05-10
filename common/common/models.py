from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .enums import JobStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AiMetadata(BaseModel):
    suggested_title: str = ""
    summary: str
    tags: list[str] = []
    category: str = ""
    key_concepts: list[str] = []


class Job(BaseModel):
    id: str
    cid: str
    title: str = ""
    status: JobStatus = JobStatus.SUBMITTED
    submitted_by: str = "anonymous"
    submitted_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    user_metadata: dict = Field(default_factory=dict)
    ai_metadata: Optional[AiMetadata] = None
    reviewer_notes: Optional[str] = None
    published_cid: Optional[str] = None


class LibraryEntry(BaseModel):
    cid: str
    title: str
    summary: str
    tags: list[str] = []
    category: str = ""
    added_at: datetime = Field(default_factory=_utcnow)
    metadata_cid: str = ""


class LibraryIndex(BaseModel):
    version: int = 1
    updated_at: datetime = Field(default_factory=_utcnow)
    entries: dict[str, LibraryEntry] = Field(default_factory=dict)
    tag_index: dict[str, list[str]] = Field(default_factory=dict)
    ipns_name: str = ""
    index_cid: str = ""

    @field_validator("entries", mode="before")
    @classmethod
    def _entries_by_cid(cls, value):
        """Accept old list-shaped library state and normalize to {cid: entry}."""
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        entries = {}
        for item in value:
            cid = item.get("cid") if isinstance(item, dict) else getattr(item, "cid", None)
            if cid:
                entries[cid] = item
        return entries
