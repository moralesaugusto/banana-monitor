"""Per-agent model-call latency, aggregated from AiRunStep - the performance companion to cost/usage."""

import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.db.session import get_databases
from app.domain.models import AiRun, AiRunStep, utcnow


async def _run_id() -> int:
    databases = get_databases()
    async with databases.app_session_factory() as session:
        run = AiRun()
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


async def _step(run_id: int, idx: int, **fields: object) -> None:
    databases = get_databases()
    async with databases.app_session_factory() as session:
        session.add(AiRunStep(run_id=run_id, idx=idx, request={}, response={}, **fields))
        await session.commit()


async def test_latency_is_averaged_per_agent_across_runs(client: AsyncClient) -> None:
    run1, run2 = await _run_id(), await _run_id()
    await _step(
        run1,
        0,
        kind="llm",
        name="m1",
        agent="discoverer",
        duration_ms=1000,
        prompt_tokens=100,
        completion_tokens=20,
    )
    await _step(
        run2,
        0,
        kind="llm",
        name="m1",
        agent="discoverer",
        duration_ms=3000,
        prompt_tokens=200,
        completion_tokens=40,
    )
    await _step(
        run1,
        1,
        kind="llm",
        name="m2",
        agent="sinverguenza",
        duration_ms=5000,
        prompt_tokens=500,
        completion_tokens=100,
    )
    await _step(run1, 2, kind="tool", name="run_nmap", agent="discoverer", duration_ms=200)

    body = (await client.get("/api/ai-mode/performance")).json()
    by_agent = {a["agent"]: a for a in body["by_agent"]}

    discoverer = by_agent["discoverer"]
    assert discoverer["calls"] == 2  # the tool step does not count
    assert discoverer["avg_duration_ms"] == 2000
    assert discoverer["min_duration_ms"] == 1000 and discoverer["max_duration_ms"] == 3000
    assert discoverer["models"] == ["m1"]
    assert discoverer["prompt_tokens"] == 300 and discoverer["completion_tokens"] == 60
    assert discoverer["tokens_per_second"] == pytest.approx(60 / 4, rel=1e-6)
    assert discoverer["errors"] == 0

    sinverguenza = by_agent["sinverguenza"]
    assert sinverguenza["calls"] == 1 and sinverguenza["models"] == ["m2"]

    by_agent_model = {(r["agent"], r["model"]): r for r in body["by_agent_model"]}
    assert by_agent_model[("discoverer", "m1")]["calls"] == 2
    assert by_agent_model[("discoverer", "m1")]["avg_duration_ms"] == 2000
    assert by_agent_model[("sinverguenza", "m2")]["calls"] == 1
    assert len(body["by_agent_model"]) == 2  # one row per (agent, model) pair, not per agent or model

    by_model = {m["model"]: m for m in body["by_model"]}
    assert by_model["m1"]["calls"] == 2 and by_model["m1"]["agents"] == ["discoverer"]
    assert by_model["m1"]["avg_duration_ms"] == 2000
    assert by_model["m2"]["agents"] == ["sinverguenza"]
    assert body["since"] is None


async def test_errors_are_counted_per_agent_without_affecting_latency(client: AsyncClient) -> None:
    run_id = await _run_id()
    await _step(run_id, 0, kind="llm", name="m1", agent="bellaco", duration_ms=1000, completion_tokens=10)
    await _step(run_id, 1, kind="error", agent="bellaco")

    body = (await client.get("/api/ai-mode/performance")).json()
    bellaco = next(a for a in body["by_agent"] if a["agent"] == "bellaco")
    assert bellaco["calls"] == 1 and bellaco["errors"] == 1


async def test_no_history_means_no_rows(client: AsyncClient) -> None:
    body = (await client.get("/api/ai-mode/performance")).json()
    assert body["by_agent"] == [] and body["by_agent_model"] == [] and body["by_model"] == []
    assert body["since"] is None


async def test_an_agent_that_switched_models_gets_one_row_per_model(client: AsyncClient) -> None:
    """The point of by_agent_model: discoverer's own blended average (by_agent) hides that it was
    fast on m1 and slow on m2 - the per-model breakdown must keep them separate."""
    run_id = await _run_id()
    await _step(run_id, 0, kind="llm", name="m1", agent="discoverer", duration_ms=1000, completion_tokens=10)
    await _step(run_id, 1, kind="llm", name="m1", agent="discoverer", duration_ms=1000, completion_tokens=10)
    await _step(run_id, 2, kind="llm", name="m2", agent="discoverer", duration_ms=9000, completion_tokens=10)

    body = (await client.get("/api/ai-mode/performance")).json()
    rows = {r["model"]: r for r in body["by_agent_model"] if r["agent"] == "discoverer"}
    assert set(rows) == {"m1", "m2"}
    assert rows["m1"]["calls"] == 2 and rows["m1"]["avg_duration_ms"] == 1000
    assert rows["m2"]["calls"] == 1 and rows["m2"]["avg_duration_ms"] == 9000

    discoverer = next(a for a in body["by_agent"] if a["agent"] == "discoverer")
    assert discoverer["calls"] == 3 and sorted(discoverer["models"]) == ["m1", "m2"]


async def test_a_model_shared_across_agents_lists_all_of_them(client: AsyncClient) -> None:
    run_id = await _run_id()
    await _step(run_id, 0, kind="llm", name="m1", agent="bellaco", duration_ms=1000, completion_tokens=10)
    await _step(
        run_id, 1, kind="llm", name="m1", agent="sinverguenza", duration_ms=3000, completion_tokens=30
    )

    body = (await client.get("/api/ai-mode/performance")).json()
    m1 = next(m for m in body["by_model"] if m["model"] == "m1")
    assert m1["calls"] == 2 and m1["agents"] == ["bellaco", "sinverguenza"]
    assert m1["avg_duration_ms"] == 2000


async def test_reset_moves_the_cutoff_without_touching_ai_run_steps(client: AsyncClient) -> None:
    run_id = await _run_id()
    old = utcnow() - datetime.timedelta(hours=1)
    await _step(run_id, 0, kind="llm", name="m1", agent="discoverer", duration_ms=1000, ts=old)

    assert (await client.post("/api/ai-mode/performance/reset")).status_code == 204
    body = (await client.get("/api/ai-mode/performance")).json()
    assert body["by_agent"] == [] and body["by_agent_model"] == [] and body["by_model"] == []
    assert body["since"] is not None

    await _step(run_id, 1, kind="llm", name="m1", agent="discoverer", duration_ms=2000)
    body = (await client.get("/api/ai-mode/performance")).json()
    assert body["by_agent"][0]["calls"] == 1  # only the post-reset step counts

    databases = get_databases()
    async with databases.app_session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(AiRunStep))
    assert count == 2  # the pre-reset step is still in run history, untouched
