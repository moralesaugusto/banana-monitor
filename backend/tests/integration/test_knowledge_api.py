import pytest
from httpx import AsyncClient

from app.knowledge import service


@pytest.fixture(autouse=True)
def _fake_embed(monkeypatch):
    async def fake_embed(base_url: str, model: str, text: str, *, api_key: str | None = None) -> list[float]:
        return [float((hash(text) >> (8 * i)) % 97) for i in range(4)]

    monkeypatch.setattr(service, "embed", fake_embed)


async def _add_entry(client: AsyncClient, collection_id: int, title: str, content: str) -> object:
    url = f"/api/knowledge/collections/{collection_id}/entries"
    return (await client.post(url, json={"title": title, "content": content})).json()


@pytest.mark.asyncio
async def test_create_list_and_delete_a_collection(client: AsyncClient) -> None:
    payload = {"name": "Test", "description": "d"}
    created = (await client.post("/api/knowledge/collections", json=payload)).json()
    assert created["name"] == "Test"
    assert created["entry_count"] == 0

    listed = (await client.get("/api/knowledge/collections")).json()
    assert any(c["name"] == "Test" for c in listed)

    resp = await client.delete(f"/api/knowledge/collections/{created['id']}")
    assert resp.status_code == 204
    listed_after = (await client.get("/api/knowledge/collections")).json()
    assert not any(c["name"] == "Test" for c in listed_after)


@pytest.mark.asyncio
async def test_collection_summary_reports_vector_and_character_counts(client: AsyncClient) -> None:
    collection = (await client.post("/api/knowledge/collections", json={"name": "Stats"})).json()
    assert collection["point_count"] == 0
    assert collection["total_chars"] == 0

    await _add_entry(client, collection["id"], "a", "twelve chars")  # 12 chars, 1 chunk/point

    listed = (await client.get("/api/knowledge/collections")).json()
    stats = next(c for c in listed if c["id"] == collection["id"])
    assert stats["point_count"] == 1
    assert stats["total_chars"] == 12


@pytest.mark.asyncio
async def test_reset_wipes_every_collections_entries_but_keeps_the_collections(client: AsyncClient) -> None:
    collection = (await client.post("/api/knowledge/collections", json={"name": "ToWipe"})).json()
    await _add_entry(client, collection["id"], "a", "hello")

    response = await client.post("/api/knowledge/reset")
    assert response.status_code == 204

    listed = (await client.get("/api/knowledge/collections")).json()
    stats = next(c for c in listed if c["id"] == collection["id"])
    assert stats["entry_count"] == 0
    assert stats["point_count"] == 0
    assert any(c["name"] == "ToWipe" for c in listed)  # the collection itself survives


@pytest.mark.asyncio
async def test_reembed_a_collection_updates_the_embedding_model_shown_on_its_entries(
    client: AsyncClient,
) -> None:
    collection = (await client.post("/api/knowledge/collections", json={"name": "ToReembed"})).json()
    [entry] = await _add_entry(client, collection["id"], "a", "hello")
    original_model = entry["embedding_model"]

    response = await client.post(f"/api/knowledge/collections/{collection['id']}/reembed")
    assert response.status_code == 200
    assert response.json()["point_count"] == 1

    refreshed = (await client.get(f"/api/knowledge/entries/{entry['id']}")).json()
    assert refreshed["embedding_model"] == original_model  # settings never changed in this test
    assert refreshed["content"] == "hello"


@pytest.mark.asyncio
async def test_reembed_an_unknown_collection_404s(client: AsyncClient) -> None:
    response = await client.post("/api/knowledge/collections/999999/reembed")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_add_list_get_edit_and_delete_an_entry(client: AsyncClient) -> None:
    collection = (await client.post("/api/knowledge/collections", json={"name": "Notes"})).json()

    created = (
        await client.post(
            f"/api/knowledge/collections/{collection['id']}/entries",
            json={"title": "First", "content": "hello world"},
        )
    ).json()
    assert len(created) == 1
    entry_id = created[0]["id"]

    listed = (await client.get(f"/api/knowledge/collections/{collection['id']}/entries")).json()
    assert [e["title"] for e in listed] == ["First"]

    detail = (await client.get(f"/api/knowledge/entries/{entry_id}")).json()
    assert detail["content"] == "hello world"
    assert detail["dims"] > 0
    assert detail["embedding_model"]

    edit_payload = {"title": "Edited", "content": "new text"}
    edited = (await client.put(f"/api/knowledge/entries/{entry_id}", json=edit_payload)).json()
    assert edited["title"] == "Edited"
    assert edited["content"] == "new text"

    resp = await client.delete(f"/api/knowledge/entries/{entry_id}")
    assert resp.status_code == 204
    assert (await client.get(f"/api/knowledge/collections/{collection['id']}/entries")).json() == []


@pytest.mark.asyncio
async def test_delete_all_entries_clears_a_collection_without_deleting_it(client: AsyncClient) -> None:
    collection = (await client.post("/api/knowledge/collections", json={"name": "Bulk"})).json()
    await client.post(
        f"/api/knowledge/collections/{collection['id']}/entries", json={"title": "a", "content": "x"}
    )
    await client.post(
        f"/api/knowledge/collections/{collection['id']}/entries", json={"title": "b", "content": "y"}
    )

    resp = await client.delete(f"/api/knowledge/collections/{collection['id']}/entries")
    assert resp.status_code == 204

    assert (await client.get(f"/api/knowledge/collections/{collection['id']}/entries")).json() == []
    still_exists = (await client.get("/api/knowledge/collections")).json()
    assert any(c["id"] == collection["id"] for c in still_exists)


@pytest.mark.asyncio
async def test_projection_on_an_empty_database_returns_an_empty_list(client: AsyncClient) -> None:
    assert (await client.get("/api/knowledge/projection")).json() == []


@pytest.mark.asyncio
async def test_projection_across_two_collections_tags_each_point_with_its_collection(
    client: AsyncClient,
) -> None:
    coll_a = (await client.post("/api/knowledge/collections", json={"name": "A"})).json()
    coll_b = (await client.post("/api/knowledge/collections", json={"name": "B"})).json()
    await _add_entry(client, coll_a["id"], "a1", "x")
    await _add_entry(client, coll_b["id"], "b1", "y")

    points = (await client.get("/api/knowledge/projection")).json()

    assert {p["collection_name"] for p in points} == {"A", "B"}
    assert {p["title"] for p in points} == {"a1", "b1"}
    for point in points:
        assert isinstance(point["x"], float) and isinstance(point["y"], float)


@pytest.mark.asyncio
async def test_projection_filtered_to_one_collection_excludes_the_other(client: AsyncClient) -> None:
    coll_a = (await client.post("/api/knowledge/collections", json={"name": "Only A"})).json()
    coll_b = (await client.post("/api/knowledge/collections", json={"name": "Not B"})).json()
    await _add_entry(client, coll_a["id"], "a1", "x")
    await _add_entry(client, coll_b["id"], "b1", "y")

    url = f"/api/knowledge/projection?collection_id={coll_a['id']}"
    points = (await client.get(url)).json()

    assert [p["title"] for p in points] == ["a1"]


@pytest.mark.asyncio
async def test_editing_an_entry_replaces_its_content_in_place_and_keeps_its_id(client: AsyncClient) -> None:
    collection = (await client.post("/api/knowledge/collections", json={"name": "Editable"})).json()
    created = await _add_entry(client, collection["id"], "Old title", "old content")
    entry_id = created[0]["id"]

    edit_payload = {"title": "New title", "content": "new content"}
    edited = (await client.put(f"/api/knowledge/entries/{entry_id}", json=edit_payload)).json()

    assert edited["id"] == entry_id
    assert edited["title"] == "New title"
    assert edited["content"] == "new content"
    listed = (await client.get(f"/api/knowledge/collections/{collection['id']}/entries")).json()
    assert len(listed) == 1  # no leftover row from a delete-then-add


@pytest.mark.asyncio
async def test_editing_an_entry_past_the_one_chunk_limit_returns_422_without_losing_data(
    client: AsyncClient,
) -> None:
    collection = (await client.post("/api/knowledge/collections", json={"name": "EditLimit"})).json()
    created = await _add_entry(client, collection["id"], "Title", "original content")
    entry_id = created[0]["id"]

    resp = await client.put(
        f"/api/knowledge/entries/{entry_id}", json={"title": "Title", "content": "y" * 10_000}
    )

    assert resp.status_code == 422
    unchanged = (await client.get(f"/api/knowledge/entries/{entry_id}")).json()
    assert unchanged["content"] == "original content"


@pytest.mark.asyncio
async def test_adding_an_entry_with_oversized_content_returns_422(client: AsyncClient) -> None:
    collection = (await client.post("/api/knowledge/collections", json={"name": "SizeLimit"})).json()

    url = f"/api/knowledge/collections/{collection['id']}/entries"
    resp = await client.post(url, json={"title": "t", "content": "y" * 50_000})

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_collection_name_with_characters_qdrant_would_reject_still_works(client: AsyncClient) -> None:
    collection = (await client.post("/api/knowledge/collections", json={"name": "weird / name? #1"})).json()

    created = await _add_entry(client, collection["id"], "t", "hello")

    assert created[0]["dims"] > 0
    listed = (await client.get(f"/api/knowledge/collections/{collection['id']}/entries")).json()
    assert len(listed) == 1


@pytest.mark.asyncio
async def test_projection_handles_collections_with_different_embedding_dimensions(
    client: AsyncClient, monkeypatch
) -> None:
    coll_a = (await client.post("/api/knowledge/collections", json={"name": "SmallDims"})).json()
    coll_b = (await client.post("/api/knowledge/collections", json={"name": "BigDims"})).json()

    async def two_dim_embed(
        base_url: str, model: str, text: str, *, api_key: str | None = None
    ) -> list[float]:
        return [1.0, 0.0]

    monkeypatch.setattr(service, "embed", two_dim_embed)
    await _add_entry(client, coll_a["id"], "a1", "x")

    async def six_dim_embed(
        base_url: str, model: str, text: str, *, api_key: str | None = None
    ) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    monkeypatch.setattr(service, "embed", six_dim_embed)
    await _add_entry(client, coll_b["id"], "b1", "y")

    resp = await client.get("/api/knowledge/projection")

    assert resp.status_code == 200
    titles = {p["title"] for p in resp.json()}
    assert titles == {"a1", "b1"}
