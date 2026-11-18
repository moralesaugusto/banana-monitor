from httpx import AsyncClient

from app.db.session import get_databases
from app.domain.models import AiRun, AiRunStep


async def _steps(*steps: tuple[str, object, object]) -> int:
    async with get_databases().app_session_factory() as session:
        run = AiRun()
        session.add(run)
        await session.flush()
        for idx, (name, request, response) in enumerate(steps):
            session.add(
                AiRunStep(run_id=run.id, idx=idx, kind="tool", name=name, request=request, response=response)
            )
        await session.commit()
        return run.id


async def test_tools_say_where_they_run_and_which_agents_hold_them(client: AsyncClient) -> None:
    await client.get("/api/ai-mode/agents")  # seeds the default agents
    tools = {t["name"]: t for t in (await client.get("/api/ai-mode/tools")).json()["tools"]}

    nc = tools["run_nc"]
    assert nc["runs_on"] == "local_program" and "nc" in nc["where"]
    assert any("single IP address" in s for s in nc["safeguards"])
    assert tools["virustotal_lookup"]["runs_on"] == "internet"
    assert tools["apply_updates"]["runs_on"] == "target_host"
    assert "discoverer" in {a["name"] for a in tools["run_nmap"]["agents"]}


async def test_usage_separates_what_worked_from_what_was_stopped(client: AsyncClient) -> None:
    assert (await client.get("/api/ai-mode/tools/usage")).json() == []
    run = await _steps(
        ("run_nmap", {"target": "10.0.0.5"}, {"exit_code": 0, "output": "80/tcp open"}),
        ("run_nmap", {"target": "8.8.8.8"}, {"error": "8.8.8.8 is not inside any configured network"}),
        ("run_nmap", {"target": "10.0.0.6"}, {"exit_code": 0, "output": "closed"}),
        ("web_search", {"query": "x"}, [{"title": "t"}]),
    )

    usage = {u["name"]: u for u in (await client.get("/api/ai-mode/tools/usage")).json()}

    nmap = usage["run_nmap"]
    assert (nmap["calls"], nmap["errors"]) == (3, 1)
    assert nmap["worked_request"] == {"target": "10.0.0.6"} and nmap["worked_run_id"] == run
    assert nmap["stopped_reason"] == "8.8.8.8 is not inside any configured network"
    assert nmap["stopped_request"] == {"target": "8.8.8.8"}
    assert (usage["web_search"]["calls"], usage["web_search"]["errors"]) == (1, 0)
    assert usage["web_search"]["stopped_reason"] is None
