import asyncio

import pytest
from sqlalchemy import select, update

from app.db.session import get_databases
from app.domain.bootstrap import ensure_default_agents
from app.domain.models import AiAgent, AiGuardrail, AiMessage, AiRunStep
from app.domain.models import Base as AppBase
from app.llm.agent import create_run
from app.llm.orchestrator import Decision, get_context, run_agent


@pytest.fixture
async def databases():
    dbs = get_databases()
    async with dbs.app_engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
    yield dbs
    await dbs.dispose()


def _reply(content=None, calls=()):
    message: dict = {"content": content}
    if calls:
        message["tool_calls"] = [
            {"id": str(n), "function": {"name": name, "arguments": args}}
            for n, (name, args) in enumerate(calls)
        ]
    return {"choices": [{"message": message}]}


async def _only_discoverer(databases, **values) -> None:
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        await session.execute(update(AiAgent).where(AiAgent.name != "discoverer").values(enabled=False))
        await session.execute(update(AiAgent).where(AiAgent.name == "discoverer").values(**values))
        await session.commit()


def _script(monkeypatch, replies):
    async def fake(**kwargs):
        return replies.pop(0)

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)


async def _tool_step(databases):
    async with databases.app_session_factory() as session:
        return await session.scalar(select(AiRunStep).where(AiRunStep.kind == "tool"))


async def test_changing_tool_always_waits_for_a_human_even_without_approval_setting(databases, monkeypatch):
    await _only_discoverer(
        databases, enabled_tools=["apply_updates"], allow_changes=True, require_approval="none"
    )
    _script(monkeypatch, [_reply(calls=[("apply_updates", '{"integration_id": 1}')]), _reply("Stopped.")])
    run_id = await create_run(databases, ["10.0.0.5"], dry_run=False)
    task = asyncio.create_task(run_agent(databases, run_id))
    held = None
    for _ in range(300):
        async with databases.app_session_factory() as session:
            held = await session.scalar(select(AiMessage).where(AiMessage.status == "held"))
        if held is not None:
            break
        await asyncio.sleep(0.01)
    assert held is not None and held.topic == "approval.tool.discoverer"
    assert held.payload["tool"] == "apply_updates"

    context = get_context(run_id)
    assert context is not None
    context.decide(held.id, Decision(False, reason="not now"))
    await asyncio.wait_for(task, 5)

    step = await _tool_step(databases)
    assert step is not None and "not now" in step.response["error"]


async def test_agent_without_allow_changes_is_refused_and_never_asks(databases, monkeypatch):
    await _only_discoverer(databases, enabled_tools=["apply_updates"], allow_changes=False)
    _script(monkeypatch, [_reply(calls=[("apply_updates", '{"integration_id": 1}')]), _reply("Refused.")])
    run_id = await create_run(databases, ["10.0.0.5"], dry_run=False)
    await asyncio.wait_for(run_agent(databases, run_id), 5)

    step = await _tool_step(databases)
    assert step is not None and "may not change hosts" in step.response["error"]
    async with databases.app_session_factory() as session:
        assert await session.scalar(select(AiMessage).where(AiMessage.status == "held")) is None


async def test_user_guardrails_apply_to_inspection_tools(databases, monkeypatch):
    await _only_discoverer(databases, enabled_tools=["ssh_readonly"])
    async with databases.app_session_factory() as session:
        session.add(AiGuardrail(name="no-uname", kind="deny_regex", pattern="uname"))
        await session.commit()
    args = '{"integration_id": 1, "command": "uname -a"}'
    _script(monkeypatch, [_reply(calls=[("ssh_readonly", args)]), _reply("Blocked.")])
    run_id = await create_run(databases, ["10.0.0.5"], dry_run=False)
    await asyncio.wait_for(run_agent(databases, run_id), 5)

    step = await _tool_step(databases)
    assert step is not None and "blocked by guardrail 'no-uname'" in step.response["error"]


async def test_api_refuses_changing_tool_without_allow_changes(client):
    agents = (await client.get("/api/ai-mode/agents")).json()
    base = {k: v for k, v in agents[0].items() if k not in ("id", "created_at", "updated_at")}
    base["enabled_tools"] = ["apply_updates"]

    refused = await client.put(
        f"/api/ai-mode/agents/{agents[0]['id']}", json={**base, "allow_changes": False}
    )
    allowed = await client.put(f"/api/ai-mode/agents/{agents[0]['id']}", json={**base, "allow_changes": True})

    assert refused.status_code == 422 and "May change hosts" in refused.json()["detail"]
    assert allowed.status_code == 200 and allowed.json()["allow_changes"] is True
