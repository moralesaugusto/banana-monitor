import datetime

from pydantic import BaseModel, Field

from app.knowledge.service import DEFAULT_CHUNK_CHARS, MAX_ENTRY_CONTENT_CHARS


class CollectionSummary(BaseModel):
    id: int
    name: str
    description: str
    entry_count: int
    point_count: int
    """Vectors actually stored in Qdrant for this collection - usually >= entry_count, since a
    long entry is chunked into several smaller pieces, each its own point."""
    total_chars: int
    """Sum of every entry's content length, in characters. The same char/4 heuristic the rest of
    this app already uses (see CHARS_PER_TOKEN_ESTIMATE in agentFields.ts) turns this into an
    approximate token count on the frontend - no tokenizer dependency, same as elsewhere."""


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class EntrySummary(BaseModel):
    id: int
    title: str
    content_excerpt: str
    source: str
    created_at: datetime.datetime
    updated_at: datetime.datetime


class EntryRead(BaseModel):
    id: int
    collection_id: int
    title: str
    content: str
    source: str
    embedding_model: str
    dims: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


class EntryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=MAX_ENTRY_CONTENT_CHARS)


class EntryUpdate(BaseModel):
    """Editing never re-chunks (see replace_entry_content) - content is capped at one chunk's
    worth, not the larger add_entry limit."""

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=DEFAULT_CHUNK_CHARS)


class ProjectionPoint(BaseModel):
    entry_id: int
    title: str
    collection_id: int
    collection_name: str
    x: float
    y: float
