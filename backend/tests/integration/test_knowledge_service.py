import pytest
from httpx import AsyncClient

from app.credentials.crypto import get_secret_box
from app.credentials.service import CredentialService
from app.db.session import get_databases
from app.domain.bootstrap import ensure_default_ai_mode_settings
from app.domain.enums import CredentialType
from app.knowledge import service
from app.knowledge.qdrant_store import get_qdrant_client, get_vector
from app.knowledge.service import (
    MAX_ENTRY_CONTENT_CHARS,
    UnknownCollectionError,
    add_entry,
    delete_all_entries,
    delete_entry,
    ensure_default_knowledge_collections,
    qdrant_key,
    reembed_collection,
    replace_entry_content,
    search,
)
from app.llm.tool_base import AgentToolError


@pytest.fixture(autouse=True)
def _fake_embed(monkeypatch):
    """Deterministic, cheap: a vector derived from the text's own characters, no network call."""

    async def fake_embed(base_url: str, model: str, text: str, *, api_key: str | None = None) -> list[float]:
        return [float((hash(text) >> (8 * i)) % 97) for i in range(4)]

    monkeypatch.setattr(service, "embed", fake_embed)


@pytest.mark.asyncio
async def test_add_entry_sends_the_configured_embedding_credential_as_an_api_key(
    client: AsyncClient, monkeypatch
) -> None:
    databases = get_databases()
    async with databases.credentials_session_factory() as session:
        credential = await CredentialService(get_secret_box()).create(
            session, "embedding host key", CredentialType.API_TOKEN, {"token": "sk-embed-secret"}
        )
    async with databases.app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
        settings.knowledge_embedding_credential_id = credential.id
        await session.commit()

    seen_api_keys: list[str | None] = []

    async def capturing_embed(base_url, model, text, *, api_key=None):  # noqa: ANN001
        seen_api_keys.append(api_key)
        return [1.0, 2.0, 3.0, 4.0]

    monkeypatch.setattr(service, "embed", capturing_embed)

    await add_entry(
        databases,
        collection_name="LAN notes",
        title="t",
        content="hello",
        source="human",
        create_collection_if_missing=True,
    )

    assert seen_api_keys == ["sk-embed-secret"]


@pytest.mark.asyncio
async def test_add_entry_rejects_an_unknown_collection_when_create_if_missing_is_false(
    client: AsyncClient,
) -> None:
    databases = get_databases()
    with pytest.raises(UnknownCollectionError):
        await add_entry(
            databases,
            collection_name="does-not-exist",
            title="t",
            content="hello",
            source="human",
            create_collection_if_missing=False,
        )


@pytest.mark.asyncio
async def test_add_entry_creates_the_collection_when_create_if_missing_is_true(client: AsyncClient) -> None:
    databases = get_databases()
    entries = await add_entry(
        databases,
        collection_name="brand new",
        title="t",
        content="hello world",
        source="human",
        create_collection_if_missing=True,
    )
    assert len(entries) == 1
    assert entries[0].title == "t"
    assert entries[0].source == "human"


@pytest.mark.asyncio
async def test_add_entry_embeds_each_chunk_and_links_them_by_parent_id(client: AsyncClient) -> None:
    databases = get_databases()
    # Two paragraphs, each under the 500-char default chunk size alone but over it combined,
    # so chunk_text splits on the paragraph boundary into exactly two chunks (not a hard split).
    para_a = ("A " * 150).strip()  # 299 chars
    para_b = ("B " * 150).strip()
    content = "\n\n".join([para_a, para_b])

    entries = await add_entry(
        databases,
        collection_name="chunked",
        title="doc",
        content=content,
        source="human",
        create_collection_if_missing=True,
    )

    assert len(entries) == 2
    assert entries[0].parent_id is None
    assert entries[1].parent_id == entries[0].id


@pytest.mark.asyncio
async def test_search_on_a_collection_with_no_entries_returns_an_empty_list(client: AsyncClient) -> None:
    databases = get_databases()
    await add_entry(
        databases,
        collection_name="empty-ish",
        title="t",
        content="x",
        source="human",
        create_collection_if_missing=True,
    )
    await delete_all_entries(databases, "empty-ish")

    assert await search(databases, collection_name="empty-ish", query="anything") == []


@pytest.mark.asyncio
async def test_search_raises_for_an_unknown_collection(client: AsyncClient) -> None:
    databases = get_databases()
    with pytest.raises(UnknownCollectionError):
        await search(databases, collection_name="nope", query="anything")


@pytest.mark.asyncio
async def test_search_finds_the_entry_it_was_given(client: AsyncClient) -> None:
    databases = get_databases()
    await add_entry(
        databases,
        collection_name="searchable",
        title="Fail2ban note",
        content="SSH on 192.168.1.2 is protected by fail2ban.",
        source="human",
        create_collection_if_missing=True,
    )

    results = await search(
        databases, collection_name="searchable", query="SSH on 192.168.1.2 is protected by fail2ban."
    )

    assert len(results) == 1
    assert results[0]["title"] == "Fail2ban note"


@pytest.mark.asyncio
async def test_search_truncates_results_to_the_injected_char_budget(client: AsyncClient) -> None:
    databases = get_databases()
    for i in range(3):
        # Each under the default chunk size, so every add_entry call produces exactly one entry
        # of exactly 400 chars - the budget math below is then exact, not chunk_text-dependent.
        await add_entry(
            databases,
            collection_name="budgeted",
            title=f"entry {i}",
            content="y" * 400,
            source="human",
            create_collection_if_missing=True,
        )

    results = await search(databases, collection_name="budgeted", query="y", top_k=3, max_injected_chars=700)

    assert len(results) == 1


@pytest.mark.asyncio
async def test_delete_entry_removes_it_from_search(client: AsyncClient) -> None:
    databases = get_databases()
    entries = await add_entry(
        databases,
        collection_name="deletable",
        title="t",
        content="x",
        source="human",
        create_collection_if_missing=True,
    )
    await delete_entry(databases, entries[0].collection_id, entries[0].id)

    assert await search(databases, collection_name="deletable", query="x") == []


@pytest.mark.asyncio
async def test_ensure_default_knowledge_collections_is_idempotent_and_only_runs_once(
    client: AsyncClient,
) -> None:
    databases = get_databases()
    await ensure_default_knowledge_collections(databases)
    await add_entry(
        databases,
        collection_name="LAN notes",
        title="t",
        content="x",
        source="human",
        create_collection_if_missing=False,
    )

    await ensure_default_knowledge_collections(databases)

    # The second call must not have wiped the entry added to a default collection in between.
    assert await search(databases, collection_name="LAN notes", query="x") != []


@pytest.mark.asyncio
async def test_add_entry_rejects_content_over_the_max_length(client: AsyncClient) -> None:
    databases = get_databases()
    with pytest.raises(AgentToolError):
        await add_entry(
            databases,
            collection_name="too-big",
            title="t",
            content="x" * (MAX_ENTRY_CONTENT_CHARS + 1),
            source="human",
            create_collection_if_missing=True,
        )


@pytest.mark.asyncio
async def test_add_entry_works_with_a_collection_name_qdrant_would_otherwise_reject(
    client: AsyncClient,
) -> None:
    # Qdrant collection names reject characters like '/' and '?'; collections are keyed by their
    # SQLite id internally, so the human-facing name is never passed to Qdrant directly.
    databases = get_databases()
    entries = await add_entry(
        databases,
        collection_name="weird / name? #1",
        title="t",
        content="hello",
        source="human",
        create_collection_if_missing=True,
    )
    assert len(entries) == 1

    results = await search(databases, collection_name="weird / name? #1", query="hello")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_add_entry_writes_nothing_if_a_later_chunk_fails_to_embed(
    client: AsyncClient, monkeypatch
) -> None:
    databases = get_databases()
    # A real entry first, so the collection exists and the later failed attempt has something
    # already-present to not disturb.
    await add_entry(
        databases,
        collection_name="atomic",
        title="existing",
        content="z",
        source="human",
        create_collection_if_missing=True,
    )

    calls = {"n": 0}

    async def flaky_embed(base_url: str, model: str, text: str, *, api_key: str | None = None) -> list[float]:
        calls["n"] += 1
        if calls["n"] == 2:
            raise AgentToolError("embedding host unreachable")
        return [1.0, 0.0, 0.0, 0.0]

    monkeypatch.setattr(service, "embed", flaky_embed)
    para_a = ("A " * 150).strip()
    para_b = ("B " * 150).strip()
    content = "\n\n".join([para_a, para_b])  # two chunks -> two embed() calls

    with pytest.raises(AgentToolError):
        await add_entry(
            databases,
            collection_name="atomic",
            title="doc",
            content=content,
            source="human",
            create_collection_if_missing=True,
        )

    # The first chunk's embed succeeded, but nothing from it should have been written to either
    # store - only the pre-existing entry is still there.
    titles = [r["title"] for r in await search(databases, collection_name="atomic", query="A", top_k=10)]
    assert titles == ["existing"]


@pytest.mark.asyncio
async def test_search_raises_a_clean_error_on_an_embedding_dimension_mismatch(
    client: AsyncClient, monkeypatch
) -> None:
    databases = get_databases()
    await add_entry(
        databases,
        collection_name="drifted",
        title="t",
        content="hello",
        source="human",
        create_collection_if_missing=True,
    )

    async def wrong_size_embed(
        base_url: str, model: str, text: str, *, api_key: str | None = None
    ) -> list[float]:
        return [1.0, 0.0]  # the collection's dimension was set to 4 by the entry above

    monkeypatch.setattr(service, "embed", wrong_size_embed)

    with pytest.raises(AgentToolError):
        await search(databases, collection_name="drifted", query="hello")


@pytest.mark.asyncio
async def test_replace_entry_content_keeps_the_same_id_and_is_found_by_the_new_text(
    client: AsyncClient,
) -> None:
    databases = get_databases()
    [entry] = await add_entry(
        databases,
        collection_name="editable",
        title="Old",
        content="old text",
        source="human",
        create_collection_if_missing=True,
    )

    updated = await replace_entry_content(databases, entry.id, title="New", content="new text")

    assert updated.id == entry.id
    assert updated.title == "New"
    assert updated.content == "new text"
    results = await search(databases, collection_name="editable", query="new text")
    assert [r["title"] for r in results] == ["New"]
    old_results = await search(databases, collection_name="editable", query="old text")
    assert all(r["entry_id"] != entry.id or r["title"] != "Old" for r in old_results)


@pytest.mark.asyncio
async def test_replace_entry_content_rejects_content_longer_than_one_chunk(client: AsyncClient) -> None:
    databases = get_databases()
    [entry] = await add_entry(
        databases,
        collection_name="editable2",
        title="Old",
        content="x",
        source="human",
        create_collection_if_missing=True,
    )

    with pytest.raises(AgentToolError):
        too_long = "y" * (service.DEFAULT_CHUNK_CHARS + 1)
        await replace_entry_content(databases, entry.id, title="New", content=too_long)


@pytest.mark.asyncio
async def test_reembed_collection_refreshes_every_entrys_vector_and_model_name(
    client: AsyncClient, monkeypatch
) -> None:
    databases = get_databases()
    entries = await add_entry(
        databases,
        collection_name="drift",
        title="a",
        content="first entry",
        source="human",
        create_collection_if_missing=True,
    )
    entries += await add_entry(
        databases, collection_name="drift", title="b", content="second entry", source="human",
        create_collection_if_missing=True,
    )
    collection_id = (await session_collection_id(databases, "drift"))

    async def new_model_embed(
        base_url: str, model: str, text: str, *, api_key: str | None = None
    ) -> list[float]:
        # A different dimensionality than _fake_embed's 4 - simulates switching to a model whose
        # vectors are a different size, the exact case that breaks a plain re-upsert.
        return [1.0, 2.0, 3.0]

    async def fake_embedding_config(databases):
        return "http://x", "new-model", None

    monkeypatch.setattr(service, "embed", new_model_embed)
    monkeypatch.setattr(service, "_embedding_config", fake_embedding_config)

    count = await reembed_collection(databases, collection_id)

    assert count == 2
    client_ = get_qdrant_client()
    for entry in entries:
        vector = await get_vector(client_, qdrant_key(collection_id), entry.id)
        assert vector is not None
        assert len(vector) == 3
    async with databases.knowledge_session_factory() as session:
        from app.knowledge.models import KnowledgeEntry

        refreshed = [await session.get(KnowledgeEntry, e.id) for e in entries]
        assert all(e.embedding_model == "new-model" for e in refreshed)


async def session_collection_id(databases, name: str) -> int:
    collection = await service._get_collection(databases, name)
    assert collection is not None
    return collection.id


@pytest.mark.asyncio
async def test_reembed_collection_on_an_unknown_id_raises(client: AsyncClient) -> None:
    with pytest.raises(UnknownCollectionError):
        await reembed_collection(get_databases(), 999999)


@pytest.mark.asyncio
async def test_reembed_collection_with_no_entries_is_a_noop(client: AsyncClient) -> None:
    databases = get_databases()
    await add_entry(
        databases, collection_name="empty-to-reembed", title="t", content="x", source="human",
        create_collection_if_missing=True,
    )
    collection_id = await session_collection_id(databases, "empty-to-reembed")
    await delete_all_entries(databases, "empty-to-reembed")

    assert await reembed_collection(databases, collection_id) == 0
