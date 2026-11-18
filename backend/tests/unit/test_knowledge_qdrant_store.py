from dataclasses import dataclass

import pytest

import app.knowledge.qdrant_store as store
from app.knowledge.qdrant_store import (
    all_points,
    delete_collection,
    delete_point,
    get_qdrant_client,
    get_vector,
    point_count,
    search,
    upsert_point,
)


@dataclass
class _FakeSettings:
    data_dir: object
    qdrant_url: str = ""

    @property
    def qdrant_local_path(self):
        return self.data_dir / "qdrant"


@pytest.fixture
def client(tmp_path, monkeypatch):
    store.get_qdrant_client.cache_clear()
    monkeypatch.setattr(store, "get_settings", lambda: _FakeSettings(data_dir=tmp_path))
    return get_qdrant_client()


@pytest.mark.asyncio
async def test_upsert_then_search_returns_the_closest_point_first(client) -> None:
    await upsert_point(client, "t", 1, [1.0, 0.0, 0.0], {"title": "a"})
    await upsert_point(client, "t", 2, [0.0, 1.0, 0.0], {"title": "b"})

    results = await search(client, "t", [1.0, 0.0, 0.0], top_k=2)

    assert results[0][0] == 1
    assert results[0][2]["title"] == "a"
    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_on_a_missing_collection_returns_an_empty_list(client) -> None:
    assert await search(client, "does-not-exist", [1.0, 0.0], top_k=5) == []


@pytest.mark.asyncio
async def test_delete_point_removes_it_from_later_searches(client) -> None:
    await upsert_point(client, "t", 1, [1.0, 0.0], {"title": "a"})
    await delete_point(client, "t", 1)

    assert await search(client, "t", [1.0, 0.0], top_k=5) == []


@pytest.mark.asyncio
async def test_delete_collection_removes_it_entirely(client) -> None:
    await upsert_point(client, "t", 1, [1.0, 0.0], {"title": "a"})
    await delete_collection(client, "t")

    assert await search(client, "t", [1.0, 0.0], top_k=5) == []


@pytest.mark.asyncio
async def test_all_points_returns_every_point_with_its_vector_and_payload(client) -> None:
    await upsert_point(client, "t", 1, [1.0, 0.0], {"title": "a"})
    await upsert_point(client, "t", 2, [0.0, 1.0], {"title": "b"})

    points = await all_points(client, "t")

    assert {p[0] for p in points} == {1, 2}
    by_id = {p[0]: (p[1], p[2]) for p in points}
    assert by_id[1] == ([1.0, 0.0], {"title": "a"})


@pytest.mark.asyncio
async def test_all_points_on_a_missing_collection_returns_an_empty_list(client) -> None:
    assert await all_points(client, "does-not-exist") == []


@pytest.mark.asyncio
async def test_point_count_reflects_upserts_and_deletes(client) -> None:
    assert await point_count(client, "t") == 0

    await upsert_point(client, "t", 1, [1.0, 0.0], {"title": "a"})
    await upsert_point(client, "t", 2, [0.0, 1.0], {"title": "b"})
    assert await point_count(client, "t") == 2

    await delete_point(client, "t", 1)
    assert await point_count(client, "t") == 1


@pytest.mark.asyncio
async def test_point_count_on_a_missing_collection_is_zero(client) -> None:
    assert await point_count(client, "does-not-exist") == 0


@pytest.mark.asyncio
async def test_get_vector_returns_a_vector_of_the_same_dimensionality(client) -> None:
    # Qdrant normalizes a cosine-distance collection's stored vectors, so this checks shape/
    # direction, not byte-exact values: get_vector's only real consumer is "how many dimensions"
    # (the knowledge-entry detail view's `dims`), never a byte-exact round trip of the original.
    await upsert_point(client, "t", 1, [2.0, 0.0, 0.0], {"title": "a"})

    vector = await get_vector(client, "t", 1)

    assert vector is not None
    assert len(vector) == 3
    assert vector[0] > 0 and vector[1] == 0 and vector[2] == 0


@pytest.mark.asyncio
async def test_get_vector_returns_none_for_a_missing_point(client) -> None:
    assert await get_vector(client, "t", 999) is None
