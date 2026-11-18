"""Token usage counters: recorded per call, broken down, and resettable."""

import pytest
from httpx import AsyncClient

from app.db.session import get_databases
from app.llm import usage as usage_module
from app.llm.agent import create_run
from app.llm.orchestrator import run_agent
from app.llm.usage import record_usage


async def _record(agent: str, prompt: int, completion: int, model: str = "m1", source: str = "agent") -> None:
    await record_usage(
        get_databases(),
        source=source,
        agent=agent,
        provider="ollama",
        model=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
    )


async def test_usage_is_summed_per_agent_model_and_in_total(client: AsyncClient) -> None:
    await _record("discoverer", 1000, 100)
    await _record("discoverer", 3000, 50)
    await _record("reviewer", 500, 20, model="m2")
    await _record("chat", 200, 10, source="assistant")
    await _record("chat", 0, 0, source="assistant")  # a reply with no usage block

    body = (await client.get("/api/ai-mode/cost")).json()

    assert body["totals"] == {
        "calls": 5,
        "prompt_tokens": 4700,
        "completion_tokens": 180,
        "total_tokens": 4880,
        "max_context_tokens": 3050,
        "calls_without_usage": 1,
    }
    by_agent = {(a["source"], a["agent"]): a for a in body["by_agent"]}
    assert by_agent[("agent", "discoverer")]["total_tokens"] == 4150
    assert by_agent[("agent", "discoverer")]["max_context_tokens"] == 3050
    assert by_agent[("agent", "reviewer")]["models"] == ["m2"]
    assert by_agent[("assistant", "chat")]["calls"] == 2
    assert [m["model"] for m in body["by_model"]] == ["m1", "m2"]
    assert len(body["by_day"]) == 1 and body["by_day"][0]["calls"] == 5
    assert body["since"] is None


async def test_reset_zeroes_the_counters_and_records_when(client: AsyncClient) -> None:
    await _record("discoverer", 1000, 100)

    assert (await client.post("/api/ai-mode/cost/reset")).status_code == 204
    body = (await client.get("/api/ai-mode/cost")).json()

    assert body["totals"]["calls"] == 0 and body["by_agent"] == []
    assert body["since"] is not None


async def test_an_agent_run_records_its_model_calls(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(**kwargs: object) -> dict:
        return {
            "choices": [{"message": {"content": "done"}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        }

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    databases = get_databases()
    run_id = await create_run(databases, ["192.168.50.7"], dry_run=False, entry_agent="discoverer")
    await run_agent(databases, run_id)

    body = (await client.get("/api/ai-mode/cost")).json()
    agent = next(a for a in body["by_agent"] if a["agent"] == "discoverer")
    assert agent["calls"] == 1 and agent["prompt_tokens"] == 120 and agent["max_context_tokens"] == 150


async def test_the_openrouter_catalog_is_priced_per_million_tokens(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_catalog() -> list[dict]:
        return [
            {
                "id": "a/b",
                "name": "AB",
                "context_length": 32000,
                "usd_per_million_in": 0.5,
                "usd_per_million_out": 1.5,
                "tools": True,
            }
        ]

    monkeypatch.setattr("app.api.routes.ai_cost.openrouter_catalog", fake_catalog)
    models = (await client.get("/api/ai-mode/cost/openrouter-models")).json()
    assert models[0]["usd_per_million_in"] == 0.5 and models[0]["tools"] is True
    assert usage_module.CATALOG_TTL_SECONDS > 0


async def test_actual_usd_prices_each_openrouter_call_at_its_own_models_real_rate(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_catalog() -> list[dict]:
        return [
            {
                "id": "a/b", "name": "AB", "context_length": 32000,
                "usd_per_million_in": 1.0, "usd_per_million_out": 2.0, "tools": True,
            }
        ]

    monkeypatch.setattr("app.llm.usage.openrouter_catalog", fake_catalog)
    await record_usage(
        get_databases(), source="agent", agent="discoverer", provider="openrouter", model="a/b",
        prompt_tokens=1_000_000, completion_tokens=500_000,
    )
    # An Ollama call must never be priced - it is free/local by definition.
    await record_usage(
        get_databases(), source="agent", agent="discoverer", provider="ollama", model="llama3",
        prompt_tokens=1_000_000, completion_tokens=1_000_000,
    )

    body = (await client.get("/api/ai-mode/cost")).json()

    assert body["actual_usd"] == pytest.approx(1.0 * 1.0 + 0.5 * 2.0)


async def test_crossing_the_cost_budget_sends_one_telegram_alert_and_not_again(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.bootstrap import ensure_default_telegram_config

    async def fake_catalog() -> list[dict]:
        return [
            {
                "id": "a/b", "name": "AB", "context_length": 32000,
                "usd_per_million_in": 10.0, "usd_per_million_out": 10.0, "tools": True,
            }
        ]

    monkeypatch.setattr("app.llm.usage.openrouter_catalog", fake_catalog)
    sent: list[tuple[float, float]] = []
    monkeypatch.setattr(
        "app.telegram.bot.notify_cost_budget_exceeded",
        lambda databases, actual, budget: sent.append((actual, budget)),
    )
    await client.put("/api/ai-mode/settings", json={"cost_budget_usd": 1.0})
    databases = get_databases()
    async with databases.app_session_factory() as session:
        config = await ensure_default_telegram_config(session)
        config.enabled = True
        await session.commit()

    async def record_openrouter_call() -> None:
        await record_usage(
            databases, source="agent", agent="discoverer", provider="openrouter", model="a/b",
            prompt_tokens=1_000_000, completion_tokens=0,
        )

    await record_openrouter_call()  # $10, already over the $1 budget
    await record_openrouter_call()  # stays over - must not alert again

    assert len(sent) == 1
    assert sent[0][0] > 1.0


async def test_changing_the_budget_rearms_the_alert(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_catalog() -> list[dict]:
        return [
            {
                "id": "a/b", "name": "AB", "context_length": 32000,
                "usd_per_million_in": 10.0, "usd_per_million_out": 0.0, "tools": True,
            }
        ]

    monkeypatch.setattr("app.llm.usage.openrouter_catalog", fake_catalog)
    sent: list[float] = []
    monkeypatch.setattr(
        "app.telegram.bot.notify_cost_budget_exceeded",
        lambda databases, actual, budget: sent.append(actual),
    )
    databases = get_databases()

    async def record_openrouter_call() -> None:
        await record_usage(
            databases, source="agent", agent="discoverer", provider="openrouter", model="a/b",
            prompt_tokens=1_000_000, completion_tokens=0,
        )

    await client.put("/api/ai-mode/settings", json={"cost_budget_usd": 1.0})
    await record_openrouter_call()
    assert len(sent) == 1

    await client.put("/api/ai-mode/settings", json={"cost_budget_usd": 2.0})
    await record_openrouter_call()

    assert len(sent) == 2


async def test_chat_calls_are_counted_as_the_chat_assistant(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(**kwargs: object) -> dict:
        return {
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
            "usage": {"prompt_tokens": 300, "completion_tokens": 20},
        }

    monkeypatch.setattr("app.llm.service.call_chat_completions", fake)
    await client.post("/api/assistant/chat", json={"message": "hello"})

    by_agent = (await client.get("/api/ai-mode/cost")).json()["by_agent"]
    chat = next(a for a in by_agent if a["source"] == "assistant")
    assert chat["calls"] == 1 and chat["total_tokens"] == 320
