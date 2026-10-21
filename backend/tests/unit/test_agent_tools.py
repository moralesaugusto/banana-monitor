import pytest

from app.db.session import get_databases
from app.domain.models import Base as AppBase
from app.domain.models import Network
from app.llm import agent_tools
from app.llm.agent import create_run
from app.llm.bus import Envelope
from app.llm.orchestrator import _message_text as message_text
from app.llm.orchestrator import run_agent


@pytest.fixture
async def databases():
    dbs = get_databases()
    async with dbs.app_engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
    async with dbs.app_session_factory() as session:
        from app.domain.bootstrap import ensure_default_site

        site = await ensure_default_site(session)
        session.add(Network(site_id=site.id, name="lan", cidr="192.168.50.0/24"))
        await session.commit()
    yield dbs
    await dbs.dispose()


async def _solo_discoverer(databases) -> None:
    """These tests exercise one agent; every other seeded agent now reacts to discoverer's result too
    (reviewer via discovery.ports.found, the rest via result.discoverer)."""
    from sqlalchemy import update

    from app.domain.bootstrap import ensure_default_agents
    from app.domain.models import AiAgent

    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        await session.execute(
            update(AiAgent).where(AiAgent.name != "discoverer").values(enabled=False)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_targets_outside_configured_networks_are_rejected(databases) -> None:
    with pytest.raises(agent_tools.AgentToolError, match="not inside"):
        await agent_tools.run_nmap(databases, {"target": "8.8.8.8"})
    with pytest.raises(agent_tools.AgentToolError, match="single IP"):
        await agent_tools.run_nmap(databases, {"target": "192.168.50.0/24"})


@pytest.mark.asyncio
async def test_disallowed_nmap_flags_are_rejected(databases) -> None:
    for bad in ("--script=vuln", "-iL", "-oN", "-sU", "-A"):
        with pytest.raises(agent_tools.AgentToolError, match="not allowed"):
            await agent_tools.run_nmap(databases, {"target": "192.168.50.5", "flags": [bad]})


@pytest.mark.asyncio
async def test_nmap_flags_accepted_as_a_space_separated_string(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model that writes flags the way the tool's own description shows them (space-separated, not a
    JSON array) must not have each character treated as its own flag."""
    captured: dict[str, object] = {}

    async def fake_run(args: list[str], timeout: float, stdin: bytes | None = None) -> dict:
        captured["args"] = args
        return {"exit_code": 0, "output": ""}

    monkeypatch.setattr(agent_tools, "_run", fake_run)
    await agent_tools.run_nmap(databases, {"target": "192.168.50.5", "flags": "-Pn -sT -sV -T4 --open"})
    assert captured["args"][:6] == ["nmap", "-Pn", "-sT", "-sV", "-T4", "--open"]
    assert captured["args"][-1] == "192.168.50.5"


@pytest.mark.asyncio
async def test_nmap_rejects_a_disallowed_flag_inside_a_string(databases) -> None:
    with pytest.raises(agent_tools.AgentToolError, match="not allowed"):
        await agent_tools.run_nmap(databases, {"target": "192.168.50.5", "flags": "-Pn -A"})


@pytest.mark.asyncio
async def test_run_nc_accepts_ports_as_a_fallback_for_port(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_nmap's parameter is plural (ports); a model reaching for the same name on this sibling tool
    must not silently fail every call."""
    captured: dict[str, object] = {}

    async def fake_run(args: list[str], timeout: float, stdin: bytes | None = None) -> dict:
        captured["args"] = args
        return {"exit_code": 0, "output": ""}

    monkeypatch.setattr(agent_tools, "_run", fake_run)
    await agent_tools.run_nc(databases, {"target": "192.168.50.5", "ports": "22"})
    assert captured["args"] == ["nc", "-n", "-w", "3", "192.168.50.5", "22"]


@pytest.mark.asyncio
async def test_run_nc_still_requires_some_port(databases) -> None:
    with pytest.raises(agent_tools.AgentToolError, match="port"):
        await agent_tools.run_nc(databases, {"target": "192.168.50.5"})


@pytest.mark.asyncio
async def test_record_service_creates_unmanaged_service_and_device(databases) -> None:
    result = await agent_tools.dispatch(
        databases,
        "record_service",
        {"ip": "192.168.50.9", "port": 5432, "service_type": "tcp", "name": "postgresql", "version": "16"},
    )
    assert result["recorded"] is True

    from sqlalchemy import select

    from app.domain.models import Service

    async with databases.app_session_factory() as session:
        service = (await session.execute(select(Service))).scalar_one()
    assert service.managed is False and service.source == "ai" and service.port == 5432
    assert service.fingerprint["name"] == "postgresql"
    assert service.device_id is not None


def _reply(content=None, calls=(), reasoning=None, usage=None) -> dict:
    message: dict = {"content": content, "reasoning": reasoning}
    if calls:
        message["tool_calls"] = [
            {"id": str(n), "function": {"name": name, "arguments": args}}
            for n, (name, args) in enumerate(calls)
        ]
    reply: dict = {"choices": [{"message": message}]}
    if usage:
        reply["usage"] = usage
    return reply


def _usage(prompt: int, completion: int) -> dict:
    return {"prompt_tokens": prompt, "completion_tokens": completion}


_RECORD_WEB = ("record_service", '{"ip": "192.168.50.7", "port": 80, "service_type": "http"}')
_REPORT_PORTS = ("report_open_ports", '{"ip": "192.168.50.7", "ports": [80]}')
_NMAP_PORT_80 = ("run_nmap", '{"target": "192.168.50.7", "ports": "80", "flags": "-Pn -sT -sV -T4 --open"}')


@pytest.mark.asyncio
async def test_agent_run_is_persisted_step_by_step(databases, monkeypatch: pytest.MonkeyPatch) -> None:
    replies = [
        _reply(calls=[_REPORT_PORTS], reasoning="check the web port", usage=_usage(100, 20)),
        _reply("Found an open web port.", usage=_usage(150, 10)),
    ]
    seen: list[dict] = []

    async def fake(**kwargs: object) -> dict:
        seen.append(kwargs)
        return replies.pop(0)

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    await _solo_discoverer(databases)
    run_id = await create_run(databases, ["192.168.50.7"], dry_run=False)
    await run_agent(databases, run_id)

    from sqlalchemy import select

    from app.domain.models import AiMessage, AiRun, AiRunStep

    async with databases.app_session_factory() as session:
        run = await session.get(AiRun, run_id)
        steps = (await session.execute(select(AiRunStep).order_by(AiRunStep.idx))).scalars().all()
        announced = await session.scalar(
            select(AiMessage).where(AiMessage.topic == "discovery.ports.found")
        )
    assert run.status == "done" and run.summary == "Found an open web port."
    assert (run.prompt_tokens, run.completion_tokens) == (250, 30)
    assert [(s.kind, s.name) for s in steps] == [
        ("llm", run.model), ("tool", "report_open_ports"), ("llm", run.model)
    ]
    assert steps[0].response["reasoning"] == "check the web port"
    assert announced is not None and announced.payload == {"ip": "192.168.50.7", "ports": [80]}
    assert seen[0]["temperature"] == 0.2


@pytest.mark.asyncio
async def test_dry_run_records_nothing_and_disabled_tools_are_hidden(databases, monkeypatch) -> None:
    from sqlalchemy import select

    from app.domain.bootstrap import ensure_default_ai_mode_settings
    from app.domain.models import AiRunStep, Service

    async with databases.app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
        settings.enabled_tools = ["record_service"]
        await session.commit()

    sent: list[dict] = []
    replies = [
        _reply(calls=[("run_nmap", '{"target": "192.168.50.7"}'), _RECORD_WEB]),
        _reply("done"),
    ]

    async def fake(**kwargs: object) -> dict:
        sent.append(kwargs)
        return replies.pop(0)

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    await _solo_discoverer(databases)
    run_id = await create_run(databases, ["192.168.50.7"], dry_run=True)
    await run_agent(databases, run_id)

    assert [t["function"]["name"] for t in sent[0]["tools"]] == ["record_service"]
    async with databases.app_session_factory() as session:
        steps = (await session.execute(select(AiRunStep).where(AiRunStep.kind == "tool"))).scalars().all()
        services = (await session.execute(select(Service))).scalars().all()
    assert "disabled" in steps[0].response["error"]
    assert steps[1].response["dry_run"] is True
    assert services == []


@pytest.mark.asyncio
async def test_llm_call_timeout_is_configurable(databases, monkeypatch: pytest.MonkeyPatch) -> None:
    """Self-hosted Ollama on modest hardware can genuinely need more than the 120s default - this must
    be a setting (AiModeSettings.llm_call_timeout_seconds), not a hardcoded constant."""
    from app.domain.bootstrap import ensure_default_ai_mode_settings

    async with databases.app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
        settings.llm_call_timeout_seconds = 300.0
        await session.commit()

    captured: list[object] = []

    async def fake(**kwargs: object) -> dict:
        captured.append(kwargs["timeout"])
        return _reply("done")

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    await _solo_discoverer(databases)
    run_id = await create_run(databases, ["192.168.50.7"], dry_run=True)
    await run_agent(databases, run_id)

    assert captured == [300.0]


@pytest.mark.asyncio
async def test_reap_orphaned_runs_spares_recent_and_active_runs(databases) -> None:
    import datetime

    from app.domain.models import AiRun, utcnow
    from app.llm import agent

    old = utcnow() - datetime.timedelta(minutes=5)
    async with databases.app_session_factory() as session:
        session.add_all(
            [
                AiRun(id=1, started_at=old),  # orphaned: should be reaped
                AiRun(id=2, started_at=old),  # still owned by this process
                AiRun(id=3, started_at=utcnow()),  # within the grace period
            ]
        )
        await session.commit()

    agent._active.add(2)
    try:
        await agent.reap_orphaned_runs(databases)
    finally:
        agent._active.discard(2)

    async with databases.app_session_factory() as session:
        statuses = {i: (await session.get(AiRun, i)).status for i in (1, 2, 3)}
    assert statuses == {1: "error", 2: "running", 3: "running"}


@pytest.mark.asyncio
async def test_failed_tool_call_keeps_the_models_arguments_in_the_trace(databases, monkeypatch) -> None:
    from sqlalchemy import select

    from app.domain.models import AiRunStep

    replies = [_reply(calls=[("report_open_ports", '{"ip": "192.168.50.7"}')]), _reply("done")]

    async def fake(**kwargs: object) -> dict:
        return replies.pop(0)

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    await _solo_discoverer(databases)
    run_id = await create_run(databases, ["192.168.50.7"], dry_run=False)
    await run_agent(databases, run_id)

    async with databases.app_session_factory() as session:
        step = (await session.execute(select(AiRunStep).where(AiRunStep.kind == "tool"))).scalar_one()
    assert step.request == {"ip": "192.168.50.7"}
    assert "required" in step.response["error"]


@pytest.mark.asyncio
async def test_two_agents_coordinate_over_the_bus(databases, monkeypatch: pytest.MonkeyPatch) -> None:
    """discoverer reports open ports -> bus announces them -> reviewer nmaps and records the service,
    which announces discovery.service.found again - but reviewer does not react to its own finding."""
    from sqlalchemy import select, update

    from app.domain.bootstrap import ensure_default_agents
    from app.domain.models import AiAgent, AiMessage, AiRunStep

    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        # reporter/bellaco/sinverguenza now also react to result.reviewer and result.discoverer -
        # out of scope for this two-agent test.
        await session.execute(
            update(AiAgent)
            .where(AiAgent.name.in_(["reporter", "bellaco", "sinverguenza"]))
            .values(enabled=False)
        )
        await session.commit()

    async def fake_run(args: list[str], timeout: float, stdin: bytes | None = None) -> dict:
        return {"exit_code": 0, "output": "80/tcp open http"}

    monkeypatch.setattr(agent_tools, "_run", fake_run)

    async def fake(**kwargs: object) -> dict:
        system = kwargs["messages"][0]["content"]  # type: ignore[index]
        history = kwargs["messages"]  # type: ignore[assignment]
        if "agent 'discoverer'" in system:
            return _reply("Reported open ports.") if len(history) > 2 else _reply(calls=[_REPORT_PORTS])
        if len(history) <= 2:
            return _reply(calls=[_NMAP_PORT_80])
        if len(history) <= 4:
            return _reply(calls=[_RECORD_WEB])
        return _reply("Identified: port 80 is http.")

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(databases, ["192.168.50.7"], dry_run=False)
    await run_agent(databases, run_id)

    async with databases.app_session_factory() as session:
        messages = (
            await session.scalars(select(AiMessage).where(AiMessage.run_id == run_id).order_by(AiMessage.id))
        ).all()
        steps = (await session.scalars(select(AiRunStep).where(AiRunStep.run_id == run_id))).all()
        for message in messages:
            await session.refresh(message, ["deliveries"])

    # The agents run concurrently, so only the causal order within each agent's own loop is fixed:
    # the task, then discoverer's announcement, strictly before discoverer's own final reply; reviewer's
    # announcement strictly before its own final reply. Order between the two loops is not fixed.
    assert [(m.topic, m.sender) for m in messages[:2]] == [
        ("task.discoverer", "human"),
        ("discovery.ports.found", "discoverer"),
    ]
    assert {(m.topic, m.sender) for m in messages[2:]} == {
        ("discovery.service.found", "reviewer"),
        ("result.discoverer", "discoverer"),
        ("result.reviewer", "reviewer"),
    }
    assert len({m.correlation_id for m in messages}) == 1  # one conversation
    ports_found = messages[1]
    assert [(d.recipient, d.state) for d in ports_found.deliveries] == [("reviewer", "acked")]
    assert [m.hops for m in messages[:2]] == [0, 1]
    service_found = next(m for m in messages if m.topic == "discovery.service.found")
    assert service_found.deliveries == []  # reviewer no longer reacts to its own announcement
    assert {s.agent for s in steps} == {"discoverer", "reviewer"}


@pytest.mark.asyncio
async def test_an_agents_own_time_budget_stops_it_without_ending_the_run(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    """bellaco gets a tiny max_run_minutes override; its own slow model call is cut short by the
    per-agent deadline sweep, independently of the run-wide backstop (which stays at the default)."""
    import asyncio

    from sqlalchemy import select, update

    from app.domain.bootstrap import ensure_default_agents
    from app.domain.models import AiAgent, AiMessage, AiRun

    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        await session.execute(
            update(AiAgent)
            .where(AiAgent.name.in_(["discoverer", "reviewer", "reporter", "sinverguenza"]))
            .values(enabled=False)
        )
        await session.execute(
            update(AiAgent).where(AiAgent.name == "bellaco").values(max_run_minutes=0.0005)  # ~30ms
        )
        await session.commit()

    monkeypatch.setattr("app.llm.orchestrator.AGENT_DEADLINE_SWEEP_SECONDS", 0.02)

    async def fake(**kwargs: object) -> dict:
        await asyncio.sleep(0.3)  # long enough for several 20ms sweep ticks to land first
        return {"choices": [{"message": {"content": "bellaco done."}}]}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(databases, [], dry_run=False, entry_agent="bellaco", message="check web1")
    await run_agent(databases, run_id)

    async with databases.app_session_factory() as session:
        run = await session.get(AiRun, run_id)
        messages = list(await session.scalars(select(AiMessage).where(AiMessage.run_id == run_id)))
    assert "result.bellaco" not in {m.topic for m in messages}  # cut short before it could answer
    assert run is not None and run.summary is not None
    assert "its own" in run.summary and "time limit" in run.summary
    assert run.stop_reason is None  # the run itself ended normally, not via the run-wide backstop


@pytest.mark.asyncio
async def test_message_approval_gate_holds_and_applies_edits(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from sqlalchemy import select, update

    from app.domain.models import AiAgent, AiMessage
    from app.llm.orchestrator import Decision, get_context

    async with databases.app_session_factory() as session:
        from app.domain.bootstrap import ensure_default_agents

        await ensure_default_agents(session)
        await session.execute(
            update(AiAgent).where(AiAgent.name == "reviewer").values(enabled=False)
        )
        await session.execute(
            update(AiAgent).where(AiAgent.name == "discoverer").values(require_approval="messages")
        )
        await session.commit()

    async def fake(**kwargs: object) -> dict:
        return _reply("All done.")

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(databases, ["192.168.50.7"], dry_run=False)
    task = asyncio.create_task(run_agent(databases, run_id))

    async def held_message() -> AiMessage:
        for _ in range(200):
            async with databases.app_session_factory() as session:
                held = await session.scalar(select(AiMessage).where(AiMessage.status == "held"))
            if held is not None:
                return held
            await asyncio.sleep(0.01)
        raise AssertionError("no message was held")

    held = await held_message()
    assert held.topic == "result.discoverer" and not task.done()  # the run waits for the human
    context = get_context(run_id)
    assert context is not None
    context.decide(held.id, Decision(True, {"text": "Edited by a human."}))
    await asyncio.wait_for(task, 5)

    async with databases.app_session_factory() as session:
        message = await session.get(AiMessage, held.id)
    assert message is not None and message.status == "delivered"
    assert message.payload == {"text": "Edited by a human."}


@pytest.mark.asyncio
async def test_tool_approval_gate_rejection_is_returned_to_the_agent(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from sqlalchemy import select, update

    from app.domain.bootstrap import ensure_default_agents
    from app.domain.models import AiAgent, AiMessage, AiRunStep
    from app.llm.orchestrator import Decision, get_context

    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        await session.execute(update(AiAgent).where(AiAgent.name == "reviewer").values(enabled=False))
        await session.execute(
            update(AiAgent).where(AiAgent.name == "discoverer").values(require_approval="tools")
        )
        await session.commit()

    replies = [_reply(calls=[_REPORT_PORTS]), _reply("Gave up.")]

    async def fake(**kwargs: object) -> dict:
        return replies.pop(0)

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(databases, ["192.168.50.7"], dry_run=False)
    task = asyncio.create_task(run_agent(databases, run_id))
    for _ in range(200):
        async with databases.app_session_factory() as session:
            held = await session.scalar(select(AiMessage).where(AiMessage.status == "held"))
        if held is not None:
            break
        await asyncio.sleep(0.01)
    assert held is not None and held.topic == "approval.tool.discoverer"
    assert held.payload["tool"] == "report_open_ports"

    context = get_context(run_id)
    assert context is not None
    context.decide(held.id, Decision(False, reason="not on my network"))
    await asyncio.wait_for(task, 5)

    async with databases.app_session_factory() as session:
        step = await session.scalar(select(AiRunStep).where(AiRunStep.kind == "tool"))
        announced = await session.scalar(
            select(AiMessage).where(AiMessage.topic == "discovery.ports.found")
        )
    assert step is not None and "not on my network" in step.response["error"]
    assert announced is None  # the tool never ran, so nothing was announced


@pytest.mark.asyncio
async def test_each_agent_calls_its_own_host_and_model(databases, monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy import update

    from app.domain.bootstrap import ensure_default_agents
    from app.domain.models import AiAgent

    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        await session.execute(
            update(AiAgent)
            .where(AiAgent.name == "reviewer")
            .values(base_url="http://gpu-box:11434/v1", model_override="qwen3:8b")
        )
        await session.commit()

    calls: list[tuple[str, str]] = []

    async def fake(**kwargs: object) -> dict:
        calls.append((str(kwargs["base_url"]), str(kwargs["model"])))
        system = kwargs["messages"][0]["content"]  # type: ignore[index]
        if "agent 'discoverer'" in system and len(kwargs["messages"]) <= 2:  # type: ignore[arg-type]
            return _reply(calls=[_REPORT_PORTS])
        return _reply("ok")

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(databases, ["192.168.50.7"], dry_run=False)
    await run_agent(databases, run_id)

    assert ("http://gpu-box:11434/v1", "qwen3:8b") in calls
    assert any(host != "http://gpu-box:11434/v1" for host, _ in calls)  # discoverer kept the default host


@pytest.mark.asyncio
async def test_dry_run_still_announces_so_other_agents_react(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select

    from app.domain.models import AiMessage

    async def fake(**kwargs: object) -> dict:
        system = kwargs["messages"][0]["content"]  # type: ignore[index]
        if "agent 'discoverer'" in system:
            history = kwargs["messages"]
            return _reply("done") if len(history) > 2 else _reply(calls=[_REPORT_PORTS])  # type: ignore[arg-type]
        return _reply("looks fine")

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(databases, ["192.168.50.7"], dry_run=True)
    await run_agent(databases, run_id)

    async with databases.app_session_factory() as session:
        found = await session.scalar(select(AiMessage).where(AiMessage.topic == "discovery.ports.found"))
        reviewed = await session.scalar(select(AiMessage).where(AiMessage.topic == "result.reviewer"))
    assert found is not None and found.payload["dry_run"] is True
    assert reviewed is not None


@pytest.mark.asyncio
async def test_scan_ports_bounds_open_sockets_by_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from app.discovery.techniques import tcp_ports

    open_now = peak = 0

    async def fake_open(host: str, port: int) -> None:
        nonlocal open_now, peak
        open_now += 1
        peak = max(peak, open_now)
        await asyncio.sleep(0)
        open_now -= 1
        raise OSError

    monkeypatch.setattr(tcp_ports.asyncio, "open_connection", fake_open)
    assert await tcp_ports.scan_ports("10.0.0.1", list(range(1, 2001)), concurrency=50) == []
    assert 0 < peak <= 50


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://192.168.50.1/", "http://169.254.169.254/", "file:///etc/passwd"])
async def test_fetch_url_refuses_non_public(databases, url):
    with pytest.raises(agent_tools.AgentToolError):
        await agent_tools.fetch_url(databases, {"url": url})


async def test_web_search_maps_results(databases, monkeypatch):
    class FakeDDGS:
        def __init__(self, **_):
            pass

        def text(self, query, max_results):
            return [{"title": "T", "href": "https://example.com", "body": f"{query}:{max_results}"}]

    monkeypatch.setattr(agent_tools, "DDGS", FakeDDGS)
    result = await agent_tools.web_search(databases, {"query": "banana", "max_results": 99})
    assert result == [{"title": "T", "url": "https://example.com", "snippet": "banana:10"}]


async def test_web_tools_are_opt_in(databases):
    with pytest.raises(agent_tools.AgentToolError):
        await agent_tools.dispatch(databases, "web_search", {"query": "x"}, enabled=["run_nmap"])


def _envelope(payload: dict) -> Envelope:
    return Envelope(
        id=1, run_id=1, topic="task.bellaco", sender="human", payload=payload,
        correlation_id="c", reply_to=None, hops=0, status="delivered",
    )


def test_message_text_spells_out_targets_separately_from_the_task_text() -> None:
    """A target list must read as unambiguously authoritative, not get flattened into the same JSON
    blob as free-text wording that could disagree with it (e.g. "every host")."""
    payload = {"text": "Check every reachable host.", "targets": ["10.0.0.5", "10.0.0.6"]}
    text = message_text(_envelope(payload))
    assert "Check every reachable host." in text
    assert "Targets (the only hosts this is about, regardless of wording above): 10.0.0.5, 10.0.0.6" in text


def test_message_text_plain_text_only_is_unchanged() -> None:
    text = message_text(_envelope({"text": "Confirmed: port 80 is http."}))
    assert text.endswith("Confirmed: port 80 is http.")
    assert "Targets" not in text


def test_message_text_carries_the_incomplete_marker() -> None:
    text = message_text(
        _envelope({"text": "Stopped at the iteration limit.", "targets": ["10.0.0.5"], "incomplete": True})
    )
    assert "Targets (the only hosts this is about, regardless of wording above): 10.0.0.5" in text
    assert '"incomplete": true' in text


@pytest.mark.asyncio
async def test_an_agent_that_exhausts_its_budget_tells_the_reporter_the_real_targets(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When bellaco never produces a real answer, reporter must not be left to guess which hosts were
    involved from nothing - the actual target list travels with the "stopped at the limit" result."""
    from sqlalchemy import select, update

    from app.domain.bootstrap import ensure_default_agents
    from app.domain.models import AiAgent, AiMessage

    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        # Only bellaco needs to run for this test; nothing else should react to its result.
        await session.execute(
            update(AiAgent).where(AiAgent.name.not_in(["bellaco"])).values(enabled=False)
        )
        await session.execute(update(AiAgent).where(AiAgent.name == "bellaco").values(max_iterations=1))
        await session.commit()

    async def fake(**kwargs: object) -> dict:
        return _reply(calls=[("list_inspect_targets", "{}")])  # never a final, content-only reply

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(databases, ["192.168.50.7"], dry_run=False, entry_agent="bellaco")
    await run_agent(databases, run_id)

    async with databases.app_session_factory() as session:
        result = await session.scalar(
            select(AiMessage).where(AiMessage.run_id == run_id, AiMessage.topic == "result.bellaco")
        )
    assert result is not None
    assert result.payload["incomplete"] is True
    assert result.payload["targets"] == ["192.168.50.7"]


@pytest.mark.asyncio
async def test_run_nc_tls_reads_a_banner_over_a_real_tls_connection(databases) -> None:
    """A plain nc connection to a TLS port returns nothing (no handshake) - tls=True must actually
    complete one and read what the service sends back."""
    import asyncio
    import ssl

    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    cert_key = _generate_self_signed_cert()
    server_ctx.load_cert_chain(*cert_key)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"hello-over-tls")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_ctx)
    port = server.sockets[0].getsockname()[1]
    try:
        result = await agent_tools.run_nc(databases, {"target": "127.0.0.1", "port": port, "tls": True})
    finally:
        server.close()
        await server.wait_closed()

    assert result["exit_code"] == 0 and result["output"] == "hello-over-tls"


@pytest.mark.asyncio
async def test_run_nc_tls_reports_a_connection_reset_instead_of_raising(databases) -> None:
    """A peer that resets the connection after the handshake used to propagate ConnectionResetError out
    of the tool and abort the whole agent; it must come back as a tool result."""
    import asyncio
    import socket
    import ssl
    import struct

    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(*_generate_self_signed_cert())

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(1)
        raw = writer.get_extra_info("socket")
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        writer.transport.abort()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_ctx)
    port = server.sockets[0].getsockname()[1]
    try:
        result = await agent_tools.run_nc(
            databases, {"target": "127.0.0.1", "port": port, "tls": True, "payload": "GET / HTTP/1.0"}
        )
    finally:
        server.close()
        await server.wait_closed()

    assert result["exit_code"] == 1 and "tls connection failed" in result["output"]


@pytest.mark.asyncio
async def test_submit_http_form_posts_fields_and_returns_truncated_body(databases) -> None:
    import asyncio

    received: dict[str, bytes] = {}

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        length = 0
        for line in head.decode().split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        body = await reader.readexactly(length) if length else b""
        received["request"] = head + body
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        result = await agent_tools.submit_http_form(
            databases,
            {"target": "127.0.0.1", "port": port, "method": "POST", "fields": {"user": "admin"}},
        )
    finally:
        server.close()
        await server.wait_closed()

    assert result["status"] == 200
    assert result["body"] == "ok"
    assert b"user=admin" in received["request"]


@pytest.mark.asyncio
async def test_submit_http_form_get_uses_a_query_string(databases) -> None:
    import asyncio

    received: dict[str, bytes] = {}

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        received["request"] = await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        result = await agent_tools.submit_http_form(
            databases,
            {"target": "127.0.0.1", "port": port, "path": "/search", "method": "GET", "fields": {"q": "x"}},
        )
    finally:
        server.close()
        await server.wait_closed()

    assert result["status"] == 200
    assert b"GET /search?q=x" in received["request"]


@pytest.mark.asyncio
async def test_submit_http_form_rejects_a_target_outside_any_configured_network(databases) -> None:
    with pytest.raises(agent_tools.AgentToolError, match="not inside"):
        await agent_tools.submit_http_form(
            databases, {"target": "8.8.8.8", "port": 80, "method": "GET", "fields": {}}
        )


@pytest.mark.asyncio
async def test_submit_http_form_dry_run_does_not_submit(databases) -> None:
    result = await agent_tools.dispatch(
        databases,
        "submit_http_form",
        {"target": "192.168.50.5", "port": 80, "method": "POST", "fields": {"a": "b"}},
        enabled=["submit_http_form"],
        dry_run=True,
    )
    assert result == {
        "submitted": False,
        "dry_run": True,
        "would_submit": {"target": "192.168.50.5", "port": 80, "method": "POST", "fields": {"a": "b"}},
    }


def _generate_self_signed_cert() -> tuple[str, str]:
    """Writes a throwaway self-signed cert+key to temp files and returns their paths."""
    import datetime
    import tempfile

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    key_bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as cert_file:
        cert_file.write(cert.public_bytes(serialization.Encoding.PEM))
    with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as key_file:
        key_file.write(key_bytes)
    return cert_file.name, key_file.name


async def test_save_report_strips_a_markdown_heading_from_the_title(databases) -> None:
    from app.domain.models import Report

    result = await agent_tools.save_report(
        databases, {"title": "## Investigation Report: 5 Hosts", "content": "x"}
    )
    async with databases.app_session_factory() as session:
        report = await session.get(Report, result["report_id"])
    assert report is not None and report.title == "Investigation Report: 5 Hosts"


async def test_reporter_falls_back_to_a_plain_snapshot_report_when_its_own_llm_call_fails(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If reporter's own LLM call fails (e.g. a real ReadTimeout), the run must not just end in
    status: error with nothing salvaged - a plain snapshot-based report is still better than nothing."""
    from sqlalchemy import select

    from app.domain.bootstrap import ensure_default_agents
    from app.domain.models import Report
    from app.llm.client import LLMRequestError

    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)

    async def fake(**kwargs: object) -> dict:
        raise LLMRequestError("ReadTimeout (no response within 120s)")

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(databases, ["127.0.0.1"], dry_run=False, entry_agent="reporter")
    await run_agent(databases, run_id)

    async with databases.app_session_factory() as session:
        reports = (await session.scalars(select(Report))).all()
    assert len(reports) == 1
    assert reports[0].title == "Reporter fallback (analysis failed)"


async def _configure_ai_mode_settings(databases, **values) -> None:
    from app.domain.bootstrap import ensure_default_ai_mode_settings

    async with databases.app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
        for key, value in values.items():
            setattr(settings, key, value)
        await session.commit()


async def test_discover_hosts_is_always_allowed_inside_a_configured_network(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_scan_cidr(databases, cidr, *, network_id=None, max_hosts=0) -> dict:
        captured.update(cidr=cidr, network_id=network_id, max_hosts=max_hosts)
        return {"hosts_scanned": 0, "hosts_up": []}

    monkeypatch.setattr(agent_tools, "scan_cidr", fake_scan_cidr)
    await agent_tools.discover_hosts(databases, {"cidr": "192.168.50.0/25"})
    assert captured["cidr"] == "192.168.50.0/25"
    assert captured["network_id"] == 1
    assert captured["max_hosts"] == agent_tools.MAX_HOSTS_PER_SCAN


async def test_discover_hosts_outside_a_network_is_rejected_by_default(databases) -> None:
    with pytest.raises(agent_tools.AgentToolError, match="turned off"):
        await agent_tools.discover_hosts(databases, {"cidr": "10.0.5.0/28"})


async def test_discover_hosts_outside_a_network_needs_a_private_range_even_when_enabled(
    databases,
) -> None:
    await _configure_ai_mode_settings(databases, allow_undefined_network_scan=True)
    with pytest.raises(agent_tools.AgentToolError, match="RFC1918"):
        await agent_tools.discover_hosts(databases, {"cidr": "8.8.8.0/28"})


async def test_discover_hosts_allows_an_undefined_private_range_once_enabled(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_scan_cidr(databases, cidr, *, network_id=None, max_hosts=0) -> dict:
        captured.update(cidr=cidr, network_id=network_id, max_hosts=max_hosts)
        return {"hosts_scanned": 0, "hosts_up": []}

    monkeypatch.setattr(agent_tools, "scan_cidr", fake_scan_cidr)
    await _configure_ai_mode_settings(
        databases, allow_undefined_network_scan=True, undefined_scan_max_hosts=64
    )
    await agent_tools.discover_hosts(databases, {"cidr": "10.0.5.0/28"})
    assert captured == {"cidr": "10.0.5.0/28", "network_id": None, "max_hosts": 64}


async def test_discover_hosts_rejects_an_undefined_range_over_its_own_cap(databases) -> None:
    await _configure_ai_mode_settings(
        databases, allow_undefined_network_scan=True, undefined_scan_max_hosts=16
    )
    with pytest.raises(agent_tools.AgentToolError, match="limit for ranges outside"):
        await agent_tools.discover_hosts(databases, {"cidr": "10.0.5.0/24"})  # 254 hosts > 16


async def test_discover_hosts_dry_run_does_not_scan(databases, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_scan_cidr(*args: object, **kwargs: object) -> dict:
        raise AssertionError("must not scan in a dry run")

    monkeypatch.setattr(agent_tools, "scan_cidr", fail_scan_cidr)
    result = await agent_tools.dispatch(
        databases, "discover_hosts", {"cidr": "192.168.50.0/25"}, enabled=["discover_hosts"], dry_run=True
    )
    assert result == {"scanned": False, "dry_run": True, "would_scan": "192.168.50.0/25"}


async def test_scan_cidr_records_a_device_with_no_network_id_outside_any_network(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real sweep (not the tool's validation layer above), driven for a CIDR that is not a
    registered Network - same funnel a Networks-page scan uses, just unattributed to any network."""
    from app.discovery import network_scanner
    from app.discovery.techniques import arp, icmp, tcp_ports
    from app.domain.models import Device

    async def fake_ping(host: str) -> bool:
        return host.endswith(".5")

    async def fake_arp_table() -> dict[str, str]:
        return {}

    async def fake_scan_ports(host: str, ports: list[int] | None = None, timeout: float = 0.5) -> list[int]:
        return []

    monkeypatch.setattr(icmp, "ping_host", fake_ping)
    monkeypatch.setattr(arp, "get_arp_table", fake_arp_table)
    monkeypatch.setattr(tcp_ports, "scan_ports", fake_scan_ports)

    result = await network_scanner.scan_cidr(databases, "10.0.9.0/29", network_id=None)
    assert result["hosts_up"] == ["10.0.9.5"]

    async with databases.app_session_factory() as session:
        from sqlalchemy import select

        device = (await session.scalars(select(Device).where(Device.primary_ip == "10.0.9.5"))).one()
    assert device.network_id is None


def test_message_text_lists_networks_and_flags_empty_ones() -> None:
    payload = {
        "text": "Go",
        "targets": ["10.0.0.1"],
        "networks": [
            {"name": "lan", "cidr": "10.0.0.0/24", "devices": 3},
            {"name": "iot", "cidr": "10.0.1.0/24", "devices": 0},
        ],
    }
    text = message_text(_envelope(payload))
    assert "lan: 10.0.0.0/24 (3 known devices)" in text
    assert "iot: 10.0.1.0/24 (0 known devices; none yet" in text


@pytest.mark.asyncio
async def test_tool_calls_from_one_model_reply_run_concurrently(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ten slow scans requested in one reply must not run back to back (each can take 60 s)."""
    import asyncio

    from sqlalchemy import select

    from app.domain.models import AiRunStep

    active = peak = 0

    async def slow_dispatch(*args: object, **kwargs: object) -> dict:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        active -= 1
        return {"exit_code": 0, "output": "ok"}

    replies = [
        _reply(calls=[("run_nmap", f'{{"target": "192.168.50.{n}", "flags": []}}') for n in range(1, 7)]),
        _reply(content="done"),
    ]

    async def fake(**kwargs: object) -> dict:
        return replies.pop(0)

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    monkeypatch.setattr("app.llm.orchestrator.dispatch", slow_dispatch)
    run_id = await create_run(databases, ["192.168.50.1"], dry_run=False, entry_agent="discoverer")
    await run_agent(databases, run_id)

    assert 1 < peak <= 4
    async with databases.app_session_factory() as session:
        tool_steps = select(AiRunStep).where(AiRunStep.run_id == run_id, AiRunStep.kind == "tool")
        steps = (await session.scalars(tool_steps)).all()
    assert len(steps) == 6


@pytest.mark.asyncio
async def test_run_nmap_adds_aggressive_lan_timeouts_unless_the_model_chose_its_own(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []

    async def fake_run(args: list[str], timeout: float, stdin: bytes | None = None) -> dict:
        seen.append(args)
        return {"exit_code": 0, "output": ""}

    monkeypatch.setattr(agent_tools, "_run", fake_run)
    await agent_tools.run_nmap(databases, {"target": "127.0.0.1", "flags": ["-sT", "-sV"]})
    own = ["-sT", "-T3", "--host-timeout=40s"]
    await agent_tools.run_nmap(databases, {"target": "127.0.0.1", "flags": own})

    assert {"-T4", "--host-timeout=30s", "--max-retries=1", "--max-rtt-timeout=500ms"} <= set(seen[0])
    assert "-T3" in seen[1] and "-T4" not in seen[1]
    assert "--host-timeout=40s" in seen[1] and "--host-timeout=30s" not in seen[1]


@pytest.mark.asyncio
async def test_a_failed_agent_still_answers_so_the_agents_waiting_for_it_start(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select, update

    from app.domain.bootstrap import ensure_default_agents
    from app.domain.models import AiAgent, AiMessage
    from app.llm.client import LLMRequestError

    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        others = AiAgent.name.not_in(["discoverer", "bellaco"])
        await session.execute(update(AiAgent).where(others).values(enabled=False))
        await session.execute(
            update(AiAgent)
            .where(AiAgent.name == "bellaco")
            .values(enabled=True, subscribes=["task.bellaco", "result.discoverer"])
        )
        await session.commit()

    calls = 0

    async def fake(**kwargs: object) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise LLMRequestError("ReadTimeout (no response within 300s)")
        return _reply(content="checked")

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(databases, ["192.168.50.7"], dry_run=False, entry_agent="discoverer")
    await run_agent(databases, run_id)

    async with databases.app_session_factory() as session:
        failure = await session.scalar(
            select(AiMessage).where(AiMessage.run_id == run_id, AiMessage.topic == "result.discoverer")
        )
        answered = await session.scalar(
            select(AiMessage).where(AiMessage.run_id == run_id, AiMessage.topic == "result.bellaco")
        )
    assert failure is not None and failure.payload["incomplete"] is True
    assert "ReadTimeout" in failure.payload["text"] and failure.payload["targets"] == ["192.168.50.7"]
    assert answered is not None


@pytest.mark.asyncio
async def test_run_nmap_says_a_skipped_host_is_not_a_clean_result(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_run(args: list[str], timeout: float, stdin: bytes | None = None) -> dict:
        return {"exit_code": 0, "output": "Skipping host 10.0.0.5 due to host timeout\n"}

    monkeypatch.setattr(agent_tools, "_run", fake_run)
    result = await agent_tools.run_nmap(databases, {"target": "127.0.0.1", "flags": ["-sT"]})

    assert "says nothing about which ports are open" in result["output"]
