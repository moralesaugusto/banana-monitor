import datetime

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.types import UTCDateTime


class KnowledgeBase(DeclarativeBase):
    pass


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class KnowledgeCollection(KnowledgeBase):
    """A named, human-curated group of KnowledgeEntry rows (e.g. "LAN notes",
    "Security knowledge", "Sandbox" - see domain.bootstrap.ensure_default_knowledge_collections)."""

    __tablename__ = "knowledge_collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)


class KnowledgeEntry(KnowledgeBase):
    """One embedded chunk of text - the authoritative record (title/content/metadata). The vector
    itself lives in Qdrant (knowledge.qdrant_store), keyed by this row's own id as the Qdrant point
    id; this table never stores the vector twice. A document longer than the chunk size
    (knowledge.service.chunk_text) becomes several rows sharing one parent_id (the first chunk's
    own id)."""

    __tablename__ = "knowledge_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("knowledge_collections.id", ondelete="CASCADE"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_entries.id"), default=None)
    title: Mapped[str]
    content: Mapped[str] = mapped_column(Text, default="")
    embedding_model: Mapped[str] = mapped_column(default="")
    """Which embedding model produced the vector stored in Qdrant for this row - lets a model change
    be noticed (a mismatch is visible here) rather than silently misranking."""
    source: Mapped[str] = mapped_column(default="human")
    """'human' or 'agent:<name>' - same attribution convention as Report.source."""
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
