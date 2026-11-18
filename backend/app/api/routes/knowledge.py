from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.deps import KnowledgeSession
from app.api.schemas.knowledge import (
    CollectionCreate,
    CollectionSummary,
    EntryCreate,
    EntryRead,
    EntrySummary,
    EntryUpdate,
    ProjectionPoint,
)
from app.db.session import get_databases
from app.knowledge.models import KnowledgeCollection, KnowledgeEntry
from app.knowledge.projection import pca_2d
from app.knowledge.qdrant_store import all_points, get_qdrant_client, get_vector, point_count
from app.knowledge.service import (
    UnknownCollectionError,
    add_entry,
    delete_all_entries,
    delete_entry,
    qdrant_key,
    reembed_collection,
    replace_entry_content,
)
from app.llm.tool_base import AgentToolError

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

EXCERPT_CHARS = 200


def _excerpt(content: str) -> str:
    return content if len(content) <= EXCERPT_CHARS else content[:EXCERPT_CHARS] + "..."


async def _collection_or_404(session: KnowledgeSession, collection_id: int) -> KnowledgeCollection:
    collection = await session.get(KnowledgeCollection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


async def _entry_or_404(session: KnowledgeSession, entry_id: int) -> KnowledgeEntry:
    entry = await session.get(KnowledgeEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


def _entry_read(entry: KnowledgeEntry, dims: int) -> EntryRead:
    return EntryRead(
        id=entry.id,
        collection_id=entry.collection_id,
        title=entry.title,
        content=entry.content,
        source=entry.source,
        embedding_model=entry.embedding_model,
        dims=dims,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


@router.get("/collections", response_model=list[CollectionSummary])
async def list_collections(session: KnowledgeSession) -> list[CollectionSummary]:
    collections = (await session.scalars(select(KnowledgeCollection))).all()
    count_stmt = select(KnowledgeEntry.collection_id, func.count()).group_by(KnowledgeEntry.collection_id)
    counts: dict[int, int] = dict((await session.execute(count_stmt)).tuples().all())
    chars_stmt = select(KnowledgeEntry.collection_id, func.sum(func.length(KnowledgeEntry.content))).group_by(
        KnowledgeEntry.collection_id
    )
    chars: dict[int, int] = dict((await session.execute(chars_stmt)).tuples().all())
    client = get_qdrant_client()
    return [
        CollectionSummary(
            id=c.id,
            name=c.name,
            description=c.description,
            entry_count=counts.get(c.id, 0),
            point_count=await point_count(client, qdrant_key(c.id)),
            total_chars=chars.get(c.id, 0),
        )
        for c in collections
    ]


@router.post("/collections", response_model=CollectionSummary, status_code=201)
async def create_collection(payload: CollectionCreate, session: KnowledgeSession) -> CollectionSummary:
    name_taken_stmt = select(KnowledgeCollection).where(KnowledgeCollection.name == payload.name)
    if (await session.scalar(name_taken_stmt)) is not None:
        raise HTTPException(status_code=409, detail="A collection with this name already exists")
    collection = KnowledgeCollection(name=payload.name, description=payload.description)
    session.add(collection)
    await session.commit()
    await session.refresh(collection)
    return CollectionSummary(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        entry_count=0,
        point_count=0,
        total_chars=0,
    )


@router.delete("/collections/{collection_id}", status_code=204)
async def remove_collection(collection_id: int, session: KnowledgeSession) -> None:
    collection = await _collection_or_404(session, collection_id)
    await delete_all_entries(get_databases(), collection.name)
    await session.delete(collection)
    await session.commit()


async def _collection_summary(
    session: KnowledgeSession, collection: KnowledgeCollection
) -> CollectionSummary:
    entry_count = await session.scalar(
        select(func.count()).where(KnowledgeEntry.collection_id == collection.id)
    )
    chars = await session.scalar(
        select(func.sum(func.length(KnowledgeEntry.content))).where(
            KnowledgeEntry.collection_id == collection.id
        )
    )
    client = get_qdrant_client()
    return CollectionSummary(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        entry_count=entry_count or 0,
        point_count=await point_count(client, qdrant_key(collection.id)),
        total_chars=chars or 0,
    )


@router.post("/collections/{collection_id}/reembed", response_model=CollectionSummary)
async def reembed(collection_id: int, session: KnowledgeSession) -> CollectionSummary:
    collection = await _collection_or_404(session, collection_id)
    try:
        await reembed_collection(get_databases(), collection_id)
    except UnknownCollectionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await _collection_summary(session, collection)


@router.get("/collections/{collection_id}/entries", response_model=list[EntrySummary])
async def list_entries(collection_id: int, session: KnowledgeSession) -> list[EntrySummary]:
    await _collection_or_404(session, collection_id)
    entries = (
        await session.scalars(select(KnowledgeEntry).where(KnowledgeEntry.collection_id == collection_id))
    ).all()
    return [
        EntrySummary(
            id=e.id,
            title=e.title,
            content_excerpt=_excerpt(e.content),
            source=e.source,
            created_at=e.created_at,
            updated_at=e.updated_at,
        )
        for e in entries
    ]


@router.post("/collections/{collection_id}/entries", response_model=list[EntryRead], status_code=201)
async def create_entry(
    collection_id: int, payload: EntryCreate, session: KnowledgeSession
) -> list[EntryRead]:
    collection = await _collection_or_404(session, collection_id)
    try:
        entries = await add_entry(
            get_databases(),
            collection_name=collection.name,
            title=payload.title,
            content=payload.content,
            source="human",
            create_collection_if_missing=False,
        )
    except UnknownCollectionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentToolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    client = get_qdrant_client()
    collection_key = qdrant_key(collection.id)
    return [_entry_read(e, len(await get_vector(client, collection_key, e.id) or [])) for e in entries]


@router.get("/entries/{entry_id}", response_model=EntryRead)
async def get_entry(entry_id: int, session: KnowledgeSession) -> EntryRead:
    entry = await _entry_or_404(session, entry_id)
    client = get_qdrant_client()
    dims = len(await get_vector(client, qdrant_key(entry.collection_id), entry.id) or [])
    return _entry_read(entry, dims)


@router.put("/entries/{entry_id}", response_model=EntryRead)
async def update_entry(entry_id: int, payload: EntryUpdate, session: KnowledgeSession) -> EntryRead:
    await _entry_or_404(session, entry_id)
    try:
        updated = await replace_entry_content(
            get_databases(), entry_id, title=payload.title, content=payload.content
        )
    except AgentToolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    client = get_qdrant_client()
    dims = len(await get_vector(client, qdrant_key(updated.collection_id), updated.id) or [])
    return _entry_read(updated, dims)


@router.delete("/entries/{entry_id}", status_code=204)
async def remove_entry(entry_id: int, session: KnowledgeSession) -> None:
    entry = await _entry_or_404(session, entry_id)
    await delete_entry(get_databases(), entry.collection_id, entry.id)


@router.delete("/collections/{collection_id}/entries", status_code=204)
async def remove_all_entries(collection_id: int, session: KnowledgeSession) -> None:
    collection = await _collection_or_404(session, collection_id)
    await delete_all_entries(get_databases(), collection.name)


@router.post("/reset", status_code=204)
async def reset_knowledge_base(session: KnowledgeSession) -> None:
    """Wipes every entry and vector in every collection, so the knowledge base can start from
    scratch - the collections themselves (and the 'seeded once' flag) are left alone, since
    re-running first-start seeding is not what clearing out test/junk content is for."""
    collections = (await session.scalars(select(KnowledgeCollection))).all()
    for collection in collections:
        await delete_all_entries(get_databases(), collection.name)


@router.get("/projection", response_model=list[ProjectionPoint])
async def get_projection(
    session: KnowledgeSession, collection_id: int | None = None
) -> list[ProjectionPoint]:
    stmt = select(KnowledgeCollection)
    if collection_id is not None:
        stmt = stmt.where(KnowledgeCollection.id == collection_id)
    collections = (await session.scalars(stmt)).all()

    client = get_qdrant_client()
    rows: list[tuple[int, str, int, str, list[float]]] = []
    for collection in collections:
        for point_id, vector, payload in await all_points(client, qdrant_key(collection.id)):
            rows.append((point_id, str(payload.get("title", "")), collection.id, collection.name, vector))

    if not rows:
        return []

    # Different collections may have been created under different embedding models, which means
    # different vector sizes - pca_2d can't build one matrix out of ragged vectors, so each
    # distinct size is projected on its own (still a valid, if separately-scaled, 2D view).
    points: list[ProjectionPoint] = []
    by_dims: dict[int, list[tuple[int, str, int, str, list[float]]]] = {}
    for row in rows:
        by_dims.setdefault(len(row[4]), []).append(row)
    for group in by_dims.values():
        projected = pca_2d([r[4] for r in group])
        points.extend(
            ProjectionPoint(entry_id=r[0], title=r[1], collection_id=r[2], collection_name=r[3], x=x, y=y)
            for r, (x, y) in zip(group, projected, strict=True)
        )
    return points
