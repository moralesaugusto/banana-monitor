"""Vector storage/search, backed by qdrant-client. Embedded (local, on-disk, no server) by
default - Settings.qdrant_url is the one line that swaps to a real Qdrant server on the LAN
later, with no other code change (QdrantClient's own url=/path= constructor arguments cover
both cases identically).

Each knowledge collection name is also the Qdrant collection name; a KnowledgeEntry's SQLite
id doubles as its Qdrant point id, so the two stores stay trivially joined without a mapping
table.

Every public function here is async even though qdrant-client itself is synchronous: each one
runs its real work via asyncio.to_thread, so a local-mode call (disk I/O, no network) never
blocks the event loop that every other agent/request shares. get_qdrant_client() is the one
exception - it only builds the client object (or returns the cached one), it does no I/O."""

import asyncio
from functools import lru_cache
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.config import get_settings


@lru_cache
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    if settings.qdrant_url:
        return QdrantClient(url=settings.qdrant_url)
    settings.qdrant_local_path.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(settings.qdrant_local_path))


def _ensure_collection(client: QdrantClient, collection: str, vector_size: int) -> None:
    if not client.collection_exists(collection):
        vectors_config = VectorParams(size=vector_size, distance=Distance.COSINE)
        client.create_collection(collection_name=collection, vectors_config=vectors_config)


def _upsert_point(
    client: QdrantClient, collection: str, point_id: int, vector: list[float], payload: dict[str, Any]
) -> None:
    _ensure_collection(client, collection, len(vector))
    point = PointStruct(id=point_id, vector=vector, payload=payload)
    client.upsert(collection_name=collection, points=[point])


async def upsert_point(
    client: QdrantClient, collection: str, point_id: int, vector: list[float], payload: dict[str, Any]
) -> None:
    await asyncio.to_thread(_upsert_point, client, collection, point_id, vector, payload)


def _search(
    client: QdrantClient, collection: str, query_vector: list[float], top_k: int
) -> list[tuple[int, float, dict[str, Any]]]:
    if not client.collection_exists(collection):
        return []
    response = client.query_points(
        collection_name=collection, query=query_vector, limit=top_k, with_payload=True
    )
    return [(int(point.id), point.score, dict(point.payload or {})) for point in response.points]


async def search(
    client: QdrantClient, collection: str, query_vector: list[float], top_k: int
) -> list[tuple[int, float, dict[str, Any]]]:
    return await asyncio.to_thread(_search, client, collection, query_vector, top_k)


def _delete_point(client: QdrantClient, collection: str, point_id: int) -> None:
    if client.collection_exists(collection):
        client.delete(collection_name=collection, points_selector=[point_id])


async def delete_point(client: QdrantClient, collection: str, point_id: int) -> None:
    await asyncio.to_thread(_delete_point, client, collection, point_id)


def _delete_collection(client: QdrantClient, collection: str) -> None:
    if client.collection_exists(collection):
        client.delete_collection(collection_name=collection)


async def delete_collection(client: QdrantClient, collection: str) -> None:
    await asyncio.to_thread(_delete_collection, client, collection)


def _as_dense_vector(vector: object) -> list[float]:
    """Every vector this module ever stores is a single unnamed dense vector (upsert_point never
    passes named/sparse/multi-vectors), so a plain list of floats is the only real shape - this
    narrows qdrant-client's broader return type to what is actually ever there."""
    if isinstance(vector, list) and (not vector or isinstance(vector[0], (int, float))):
        return [float(v) for v in vector]
    return []


def _all_points(
    client: QdrantClient, collection: str, limit: int
) -> list[tuple[int, list[float], dict[str, Any]]]:
    if not client.collection_exists(collection):
        return []
    records, _next_offset = client.scroll(
        collection_name=collection, limit=limit, with_vectors=True, with_payload=True
    )
    return [(int(r.id), _as_dense_vector(r.vector), dict(r.payload or {})) for r in records]


async def all_points(
    client: QdrantClient, collection: str, limit: int = 10_000
) -> list[tuple[int, list[float], dict[str, Any]]]:
    """Every point in a collection, with its vector and payload - for the PCA projection. One page
    (limit points) is enough at this project's scale; a collection past that would need real
    pagination, not implemented here."""
    return await asyncio.to_thread(_all_points, client, collection, limit)


def _point_count(client: QdrantClient, collection: str) -> int:
    if not client.collection_exists(collection):
        return 0
    return client.count(collection_name=collection, exact=True).count


async def point_count(client: QdrantClient, collection: str) -> int:
    """How many vectors a collection actually holds - an exact count, not an estimate, since this
    only ever runs for a human-facing stats display, never a hot path."""
    return await asyncio.to_thread(_point_count, client, collection)


def _get_vector(client: QdrantClient, collection: str, point_id: int) -> list[float] | None:
    if not client.collection_exists(collection):
        return None
    records = client.retrieve(collection_name=collection, ids=[point_id], with_vectors=True)
    if not records:
        return None
    return _as_dense_vector(records[0].vector)


async def get_vector(client: QdrantClient, collection: str, point_id: int) -> list[float] | None:
    return await asyncio.to_thread(_get_vector, client, collection, point_id)
