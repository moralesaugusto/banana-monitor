"""AI Mode agents on Ollama or OpenRouter: default and per agent."""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import get_databases
from app.domain.models import AiRun
from app.llm.agent import create_run
from app.llm.client import LLMRequestError
from app.llm.orchestrator import run_agent

KEY = "sk-or-test-key-123456"


async def _credential(client: AsyncClient) -> int:
    response = await client.post(
        "/api/credentials",
        json={"label": "openrouter", "credential_type": "api_token", "secret": {"token": KEY}},
    )
    return response.json()["id"]


async def _agent(client: AsyncClient, name: str) -> dict:
    return next(a for a in (await client.get("/api/ai-mode/agents")).json() if a["name"] == name)


def _body(agent: dict, **changes: object) -> dict:
    keep = ("name", "display_name", "role", "system_prompt", "base_url", "model_override", "temperature")
    body = {k: agent[k] for k in keep + ("max_iterations", "enabled_tools", "subscribes", "publishes")}
    return {**body, **changes}


async def test_default_openrouter_needs_a_credential(client: AsyncClient) -> None:
    response = await client.put("/api/ai-mode/settings", json={"llm_provider": "openrouter"})
    assert response.status_code == 422

    key_id = await _credential(client)
    response = await client.put(
        "/api/ai-mode/settings",
        json={
            "llm_provider": "openrouter",
            "llm_credential_id": key_id,
            "llm_base_url": "https://openrouter.ai/api/v1",
            "llm_model": "x/y:free",
        },
    )
    assert response.status_code == 200 and response.json()["llm_provider"] == "openrouter"
    assert KEY not in response.text


async def test_an_agent_on_another_provider_needs_its_own_model(client: AsyncClient) -> None:
    agent = await _agent(client, "reviewer")
    key_id = await _credential(client)

    no_model = await client.put(
        f"/api/ai-mode/agents/{agent['id']}",
        json=_body(agent, provider="openrouter", credential_id=key_id),
    )
    assert no_model.status_code == 422

    no_key = await client.put(
        f"/api/ai-mode/agents/{agent['id']}",
        json=_body(agent, provider="openrouter", model_override="x/y:free"),
    )
    assert no_key.status_code == 422

    ok = await client.put(
        f"/api/ai-mode/agents/{agent['id']}",
        json=_body(agent, provider="openrouter", credential_id=key_id, model_override="x/y:free"),
    )
    assert ok.status_code == 200 and ok.json()["provider"] == "openrouter"
    assert KEY not in ok.text


async def test_run_sends_the_key_only_to_the_openrouter_agents(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_id = await _credential(client)
    discoverer = await _agent(client, "discoverer")
    await client.put(
        f"/api/ai-mode/agents/{discoverer['id']}",
        json=_body(
            discoverer,
            provider="openrouter",
            credential_id=key_id,
            model_override="x/y:free",
            max_iterations=1,
        ),
    )
    seen: list[tuple[str, str, str | None]] = []

    async def fake(**kwargs: object) -> dict:
        seen.append((str(kwargs["base_url"]), str(kwargs["model"]), kwargs["api_key"]))  # type: ignore[arg-type]
        return {"choices": [{"message": {"content": "done"}}]}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    databases = get_databases()
    run_id = await create_run(databases, ["192.168.50.7"], dry_run=False, entry_agent="discoverer")
    await run_agent(databases, run_id)

    assert seen[0] == ("https://openrouter.ai/api/v1", "x/y:free", KEY)
    async with databases.app_session_factory() as session:
        run = await session.scalar(select(AiRun).where(AiRun.id == run_id))
    assert run is not None
    assert KEY not in json.dumps(run.settings_snapshot)
    assert all(a["provider"] in ("ollama", "openrouter") for a in run.settings_snapshot["agents"])


async def test_fallback_provider_needs_its_own_model_and_credential(client: AsyncClient) -> None:
    agent = await _agent(client, "reviewer")
    key_id = await _credential(client)

    no_model = await client.put(
        f"/api/ai-mode/agents/{agent['id']}",
        json=_body(agent, fallback_provider="openrouter", fallback_credential_id=key_id),
    )
    assert no_model.status_code == 422

    no_key = await client.put(
        f"/api/ai-mode/agents/{agent['id']}",
        json=_body(agent, fallback_provider="openrouter", fallback_model="x/y:free"),
    )
    assert no_key.status_code == 422

    ok = await client.put(
        f"/api/ai-mode/agents/{agent['id']}",
        json=_body(
            agent, fallback_provider="openrouter", fallback_credential_id=key_id, fallback_model="x/y:free"
        ),
    )
    assert ok.status_code == 200 and ok.json()["fallback_provider"] == "openrouter"
    assert KEY not in ok.text


async def test_run_retries_once_on_the_fallback_model_when_the_primary_call_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_id = await _credential(client)
    discoverer = await _agent(client, "discoverer")
    await client.put(
        f"/api/ai-mode/agents/{discoverer['id']}",
        json=_body(
            discoverer,
            max_iterations=1,
            fallback_provider="openrouter",
            fallback_credential_id=key_id,
            fallback_model="x/y:free",
        ),
    )
    seen: list[str] = []

    async def fake(**kwargs: object) -> dict:
        seen.append(str(kwargs["model"]))
        if len(seen) == 1:
            raise LLMRequestError("primary model unreachable")
        return {"choices": [{"message": {"content": "done via fallback"}}]}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    databases = get_databases()
    run_id = await create_run(databases, ["192.168.50.7"], dry_run=False, entry_agent="discoverer")
    await run_agent(databases, run_id)

    assert seen[0] == "qwen3:8b"  # primary, fails
    assert seen[1] == "x/y:free"  # fallback, retried once and succeeds
    async with databases.app_session_factory() as session:
        run = await session.scalar(select(AiRun).where(AiRun.id == run_id))
    assert run is not None
    assert run.error is None


async def test_run_fails_normally_when_the_primary_call_fails_with_no_fallback_configured(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    discoverer = await _agent(client, "discoverer")
    await client.put(f"/api/ai-mode/agents/{discoverer['id']}", json=_body(discoverer, max_iterations=1))

    async def fake(**kwargs: object) -> dict:
        raise LLMRequestError("primary model unreachable")

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    databases = get_databases()
    run_id = await create_run(databases, ["192.168.50.7"], dry_run=False, entry_agent="discoverer")
    await run_agent(databases, run_id)

    async with databases.app_session_factory() as session:
        run = await session.scalar(select(AiRun).where(AiRun.id == run_id))
    assert run is not None
    assert run.error is not None
