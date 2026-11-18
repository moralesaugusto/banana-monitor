import pytest
from httpx import AsyncClient

from app.db.session import get_databases
from app.domain.bootstrap import ensure_default_ai_mode_settings
from app.knowledge import service
from app.llm.agent_tools import dispatch
from app.llm.tool_base import AgentToolError


@pytest.fixture(autouse=True)
def _fake_embed(monkeypatch):
    async def fake_embed(base_url: str, model: str, text: str, *, api_key: str | None = None) -> list[float]:
        return [float((hash(text) >> (8 * i)) % 97) for i in range(4)]

    monkeypatch.setattr(service, "embed", fake_embed)


async def _set_knowledge_base_enabled(enabled: bool) -> None:
    databases = get_databases()
    async with databases.app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
        settings.knowledge_base_enabled = enabled
        await session.commit()


@pytest.mark.asyncio
async def test_search_knowledge_is_refused_when_the_master_toggle_is_off_even_if_the_agent_holds_it(
    client: AsyncClient,
) -> None:
    databases = get_databases()
    await service.add_entry(
        databases,
        collection_name="LAN notes",
        title="t",
        content="hello",
        source="human",
        create_collection_if_missing=True,
    )

    with pytest.raises(AgentToolError):
        await dispatch(
            databases,
            "search_knowledge",
            {"collection": "LAN notes", "query": "hello"},
            enabled=["search_knowledge"],
        )


@pytest.mark.asyncio
async def test_search_knowledge_rejects_a_non_numeric_top_k_cleanly(client: AsyncClient) -> None:
    databases = get_databases()
    await service.add_entry(
        databases,
        collection_name="LAN notes",
        title="t",
        content="hello",
        source="human",
        create_collection_if_missing=True,
    )
    await _set_knowledge_base_enabled(True)

    with pytest.raises(AgentToolError):
        await dispatch(
            databases,
            "search_knowledge",
            {"collection": "LAN notes", "query": "hello", "top_k": "a lot"},
            enabled=["search_knowledge"],
        )


@pytest.mark.asyncio
async def test_search_knowledge_returns_ranked_results_when_enabled(client: AsyncClient) -> None:
    databases = get_databases()
    await service.add_entry(
        databases,
        collection_name="LAN notes",
        title="Fail2ban note",
        content="SSH is protected by fail2ban.",
        source="human",
        create_collection_if_missing=True,
    )
    await _set_knowledge_base_enabled(True)

    result = await dispatch(
        databases,
        "search_knowledge",
        {"collection": "LAN notes", "query": "SSH is protected by fail2ban."},
        enabled=["search_knowledge"],
    )

    assert result[0]["title"] == "Fail2ban note"


@pytest.mark.asyncio
async def test_add_knowledge_entry_rejects_an_unknown_collection_with_a_clear_message(
    client: AsyncClient,
) -> None:
    await _set_knowledge_base_enabled(True)
    databases = get_databases()

    with pytest.raises(AgentToolError, match="no such collection"):
        await dispatch(
            databases,
            "add_knowledge_entry",
            {"collection": "nope", "title": "t", "content": "x"},
            enabled=["add_knowledge_entry"],
        )


@pytest.mark.asyncio
async def test_dry_run_of_add_knowledge_entry_does_not_write_anything(client: AsyncClient) -> None:
    await _set_knowledge_base_enabled(True)
    databases = get_databases()
    await service.add_entry(
        databases,
        collection_name="LAN notes",
        title="real entry",
        content="hello",
        source="human",
        create_collection_if_missing=True,
    )

    result = await dispatch(
        databases,
        "add_knowledge_entry",
        {"collection": "LAN notes", "title": "dry run entry", "content": "x"},
        enabled=["add_knowledge_entry"],
        dry_run=True,
    )

    assert result == {"saved": False, "dry_run": True}
    titles = [r["title"] for r in await service.search(databases, collection_name="LAN notes", query="hello")]
    assert titles == ["real entry"]


@pytest.mark.asyncio
async def test_search_knowledge_surfaces_an_embedding_model_mismatch_as_a_clean_tool_error(
    client: AsyncClient, monkeypatch
) -> None:
    databases = get_databases()
    await _set_knowledge_base_enabled(True)
    await service.add_entry(
        databases,
        collection_name="LAN notes",
        title="t",
        content="hello",
        source="human",
        create_collection_if_missing=True,
    )

    async def wrong_size_embed(
        base_url: str, model: str, text: str, *, api_key: str | None = None
    ) -> list[float]:
        return [1.0, 0.0]

    monkeypatch.setattr(service, "embed", wrong_size_embed)

    # A clean AgentToolError, not a bare ValueError that would escape dispatch() uncaught.
    with pytest.raises(AgentToolError):
        await dispatch(
            databases,
            "search_knowledge",
            {"collection": "LAN notes", "query": "hello"},
            enabled=["search_knowledge"],
        )
