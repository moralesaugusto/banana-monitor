"""Chunking plus the human/agent-facing entry-management functions. SQLite (KnowledgeEntry)
stays the authoritative text/metadata store; Qdrant holds the vector and a payload copy of
the text (so a search needs no SQLite round-trip), keyed by the entry's own SQLite id as the
Qdrant point id.

Each Qdrant collection is keyed by the owning KnowledgeCollection's id (`qdrant_key`), never by
its human-entered name directly: a name is free text a person can type anything into (including
characters like '/' or '?' that Qdrant's own collection-name rules reject), while the id is a
stable, always-valid key - this is also what makes renaming a collection safe later."""

from sqlalchemy import select

from app.db.session import Databases
from app.domain.bootstrap import ensure_default_ai_mode_settings
from app.knowledge.embeddings import embed
from app.knowledge.models import KnowledgeCollection, KnowledgeEntry
from app.knowledge.qdrant_store import delete_collection as qdrant_delete_collection
from app.knowledge.qdrant_store import delete_point as qdrant_delete_point
from app.knowledge.qdrant_store import get_qdrant_client, upsert_point
from app.knowledge.qdrant_store import search as qdrant_search
from app.llm.provider import load_api_key
from app.llm.tool_base import AgentToolError

DEFAULT_CHUNK_CHARS = 500
MAX_ENTRY_CONTENT_CHARS = 20_000
"""Caps add_entry's content before chunking - about 40 chunks' worth. Without a bound here, one
paste could mean hundreds of embedding calls inside a single request (see docs/decisions.md)."""
DEFAULT_COLLECTIONS = ("LAN notes", "Security knowledge", "Sandbox")


class UnknownCollectionError(AgentToolError):
    pass


def qdrant_key(collection_id: int) -> str:
    return f"kc_{collection_id}"


def chunk_text(content: str, max_chars: int = DEFAULT_CHUNK_CHARS) -> list[str]:
    """Splits on blank-line paragraph boundaries, merging consecutive short paragraphs up to
    max_chars; a single paragraph longer than max_chars is hard-split (never silently dropped)."""
    content = content.strip()
    if not content:
        return []
    if len(content) <= max_chars:
        return [content]

    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(paragraph) <= max_chars:
            current = paragraph
        else:
            for i in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[i : i + max_chars])
    if current:
        chunks.append(current)
    return chunks


async def _embedding_config(databases: Databases) -> tuple[str, str, str | None]:
    async with databases.app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
        base_url = settings.knowledge_embedding_base_url or settings.llm_base_url
        model = settings.knowledge_embedding_model
        credential_id = settings.knowledge_embedding_credential_id
    api_key = await load_api_key(databases, credential_id)
    return base_url, model, api_key


async def _get_collection(databases: Databases, name: str) -> KnowledgeCollection | None:
    async with databases.knowledge_session_factory() as session:
        stmt = select(KnowledgeCollection).where(KnowledgeCollection.name == name)
        result: KnowledgeCollection | None = await session.scalar(stmt)
        return result


async def _unknown_collection_error(databases: Databases, name: str) -> UnknownCollectionError:
    async with databases.knowledge_session_factory() as session:
        names = (await session.scalars(select(KnowledgeCollection.name))).all()
    return UnknownCollectionError(f"no such collection {name!r}; valid collections: {sorted(names)}")


def _as_vector_error(exc: ValueError) -> AgentToolError:
    """qdrant-client raises a bare ValueError when a vector's length doesn't match the
    collection's own (fixed at its first write) - almost always the embedding model/host was
    changed after this collection was created. Turned into a clean, catchable tool error instead
    of an uncaught exception that would otherwise end the agent's turn."""
    return AgentToolError(
        f"the embedding model may have changed since this collection was created: {exc}"
    )


async def add_entry(
    databases: Databases,
    *,
    collection_name: str,
    title: str,
    content: str,
    source: str,
    create_collection_if_missing: bool,
) -> list[KnowledgeEntry]:
    if len(content) > MAX_ENTRY_CONTENT_CHARS:
        raise AgentToolError(f"content is too long (max {MAX_ENTRY_CONTENT_CHARS} characters)")
    base_url, model, api_key = await _embedding_config(databases)
    chunks = chunk_text(content)
    if not chunks:
        raise AgentToolError("content is empty")

    # Embed every chunk before writing anything, so a failure partway through (a bad chunk, the
    # embedding host going down) leaves neither store touched - never a chunk in Qdrant whose
    # SQLite row got rolled back, or vice versa.
    vectors = [await embed(base_url, model, chunk, api_key=api_key) for chunk in chunks]

    client = get_qdrant_client()
    async with databases.knowledge_session_factory() as session:
        stmt = select(KnowledgeCollection).where(KnowledgeCollection.name == collection_name)
        collection = await session.scalar(stmt)
        if collection is None:
            if not create_collection_if_missing:
                raise await _unknown_collection_error(databases, collection_name)
            collection = KnowledgeCollection(name=collection_name)
            session.add(collection)
            await session.flush()
        collection_key = qdrant_key(collection.id)

        entries: list[KnowledgeEntry] = []
        parent_id: int | None = None
        try:
            for chunk, vector in zip(chunks, vectors, strict=True):
                entry = KnowledgeEntry(
                    collection_id=collection.id,
                    parent_id=parent_id,
                    title=title,
                    content=chunk,
                    embedding_model=model,
                    source=source,
                )
                session.add(entry)
                await session.flush()
                if parent_id is None:
                    parent_id = entry.id
                await upsert_point(
                    client,
                    collection_key,
                    entry.id,
                    vector,
                    {"title": title, "content": chunk, "embedding_model": model},
                )
                entries.append(entry)
        except ValueError as exc:
            await session.rollback()
            for entry in entries:
                await qdrant_delete_point(client, collection_key, entry.id)
            raise _as_vector_error(exc) from exc
        await session.commit()
        for entry in entries:
            await session.refresh(entry)
        return entries


async def search(
    databases: Databases, *, collection_name: str, query: str, top_k: int = 5, max_injected_chars: int = 4000
) -> list[dict[str, object]]:
    collection = await _get_collection(databases, collection_name)
    if collection is None:
        raise await _unknown_collection_error(databases, collection_name)

    base_url, model, api_key = await _embedding_config(databases)
    query_vector = await embed(base_url, model, query, api_key=api_key)
    client = get_qdrant_client()
    try:
        ranked = await qdrant_search(client, qdrant_key(collection.id), query_vector, top_k)
    except ValueError as exc:
        raise _as_vector_error(exc) from exc

    results: list[dict[str, object]] = []
    used_chars = 0
    for entry_id, score, payload in ranked:
        text = str(payload.get("content", ""))
        if results and used_chars + len(text) > max_injected_chars:
            break
        results.append(
            {
                "entry_id": entry_id,
                "title": payload.get("title", ""),
                "content": text,
                "score": score,
                "embedding_model": payload.get("embedding_model", ""),
            }
        )
        used_chars += len(text)
    return results


async def replace_entry_content(
    databases: Databases, entry_id: int, *, title: str, content: str
) -> KnowledgeEntry:
    """Edits an entry in place: same id, same Qdrant point, never a delete-then-add. Content must
    still fit in one chunk - editing never re-chunks (a human wanting several chunks' worth should
    delete this entry and add the longer text fresh, so it gets chunked properly)."""
    if len(content) > DEFAULT_CHUNK_CHARS:
        raise AgentToolError(
            f"content is too long to edit in place (max {DEFAULT_CHUNK_CHARS} characters) - "
            "delete this entry and add the new text instead, so it is chunked properly"
        )
    base_url, model, api_key = await _embedding_config(databases)
    vector = await embed(base_url, model, content, api_key=api_key)

    async with databases.knowledge_session_factory() as session:
        entry = await session.get(KnowledgeEntry, entry_id)
        if entry is None:
            raise AgentToolError(f"no such entry {entry_id}")
        entry_key = qdrant_key(entry.collection_id)
        client = get_qdrant_client()
        try:
            await upsert_point(
                client,
                entry_key,
                entry.id,
                vector,
                {"title": title, "content": content, "embedding_model": model},
            )
        except ValueError as exc:
            raise _as_vector_error(exc) from exc
        entry.title = title
        entry.content = content
        entry.embedding_model = model
        await session.commit()
        await session.refresh(entry)
        return entry


async def delete_entry(databases: Databases, collection_id: int, entry_id: int) -> None:
    async with databases.knowledge_session_factory() as session:
        entry = await session.get(KnowledgeEntry, entry_id)
        if entry is not None:
            await session.delete(entry)
            await session.commit()
    await qdrant_delete_point(get_qdrant_client(), qdrant_key(collection_id), entry_id)


async def reembed_collection(databases: Databases, collection_id: int) -> int:
    """Re-embeds every entry in a collection under the current embedding settings - the fix for
    the model-drift trap: an entry already remembers which model made its vector (so a mismatch
    is visible), but until now nothing let you act on it short of deleting and retyping every
    entry. Embeds everything first (same atomicity principle as add_entry) before touching either
    store - a failure partway through an embedding host call leaves the collection exactly as it
    was. Qdrant's collection-level vector size is fixed at creation, so a model with a different
    dimensionality needs the whole Qdrant collection recreated, not just its points replaced;
    that recreation only happens once every new vector already exists in memory. Returns how many
    entries were re-embedded."""
    async with databases.knowledge_session_factory() as session:
        collection = await session.get(KnowledgeCollection, collection_id)
        if collection is None:
            raise UnknownCollectionError(f"no such collection id {collection_id}")
        stmt = select(KnowledgeEntry).where(KnowledgeEntry.collection_id == collection_id)
        entry_rows = [(e.id, e.title, e.content) for e in (await session.scalars(stmt)).all()]

    if not entry_rows:
        return 0

    base_url, model, api_key = await _embedding_config(databases)
    vectors = [await embed(base_url, model, content, api_key=api_key) for _id, _title, content in entry_rows]

    client = get_qdrant_client()
    collection_key = qdrant_key(collection_id)
    await qdrant_delete_collection(client, collection_key)
    for (entry_id, title, content), vector in zip(entry_rows, vectors, strict=True):
        payload = {"title": title, "content": content, "embedding_model": model}
        await upsert_point(client, collection_key, entry_id, vector, payload)

    async with databases.knowledge_session_factory() as session:
        for entry_id, _title, _content in entry_rows:
            entry = await session.get(KnowledgeEntry, entry_id)
            assert entry is not None  # nothing else deletes entries concurrently in this app
            entry.embedding_model = model
        await session.commit()
    return len(entry_rows)


async def delete_all_entries(databases: Databases, collection_name: str) -> None:
    collection = await _get_collection(databases, collection_name)
    if collection is None:
        raise await _unknown_collection_error(databases, collection_name)
    async with databases.knowledge_session_factory() as session:
        stmt = select(KnowledgeEntry).where(KnowledgeEntry.collection_id == collection.id)
        entries = (await session.scalars(stmt)).all()
        for entry in entries:
            await session.delete(entry)
        await session.commit()
    await qdrant_delete_collection(get_qdrant_client(), qdrant_key(collection.id))


async def ensure_default_knowledge_collections(databases: Databases) -> None:
    """One-shot (AiModeSettings.knowledge_collections_seeded): creates the default collections
    if they don't already exist. Same pattern as domain.bootstrap.ensure_default_agents's
    one-shot flags, but spans two databases (the flag lives in app.db, the collections in
    knowledge.db), so it takes `Databases` rather than a single session."""
    async with databases.app_session_factory() as app_session:
        settings = await ensure_default_ai_mode_settings(app_session)
        if settings.knowledge_collections_seeded:
            return
        async with databases.knowledge_session_factory() as session:
            existing = set((await session.scalars(select(KnowledgeCollection.name))).all())
            for name in DEFAULT_COLLECTIONS:
                if name not in existing:
                    session.add(KnowledgeCollection(name=name))
            await session.commit()
        settings.knowledge_collections_seeded = True
        await app_session.commit()
