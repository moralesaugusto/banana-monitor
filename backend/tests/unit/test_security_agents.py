import json

import pytest
from sqlalchemy import select, update

from app.db.session import get_databases
from app.domain.bootstrap import (
    LEGACY_REPORTER_PROMPT,
    LEGACY_REPORTER_PROMPT_WITH_MAESTRO,
    LEGACY_REVIEWER_PROMPT,
    LEGACY_REVIEWER_PROMPT_PRE_NMAP,
    LEGACY_SINVERGUENZA_PROMPT,
    REPORTER_PROMPT,
    REPORTER_PROMPT_PRE_REVIEWER,
    REVIEWER_PROMPT,
    SINVERGUENZA_PROMPT,
    ensure_default_agents,
    ensure_default_ai_mode_settings,
)
from app.domain.models import AiAgent, AiMessage, AiRunStep
from app.domain.models import Base as AppBase
from app.llm.agent import create_run
from app.llm.orchestrator import run_agent

NEW = ("bellaco", "sinverguenza")


@pytest.fixture
async def databases():
    dbs = get_databases()
    async with dbs.app_engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
    yield dbs
    await dbs.dispose()


async def _agents(databases) -> dict[str, AiAgent]:
    async with databases.app_session_factory() as session:
        return {a.name: a for a in await session.scalars(select(AiAgent))}


async def test_fresh_install_seeds_all_five_with_the_right_powers(databases):
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
    agents = await _agents(databases)

    assert set(agents) == {"discoverer", "reviewer", "reporter", "tajonaso", *NEW}
    assert agents["bellaco"].allow_changes is True and "apply_updates" in agents["bellaco"].enabled_tools
    for name in ("sinverguenza", "reporter", "discoverer"):
        assert agents[name].allow_changes is False and "apply_updates" not in agents[name].enabled_tools
    assert "save_report" not in agents["sinverguenza"].enabled_tools  # investigates, never reports itself
    assert "virustotal_lookup" not in agents["sinverguenza"].enabled_tools  # internet access is opt-in
    assert not any(
        "virustotal_lookup" in a.enabled_tools or "web_search" in a.enabled_tools for a in agents.values()
    )
    assert ["result.reviewer", "result.discoverer", *(f"result.{n}" for n in NEW)] == [
        t for t in agents["reporter"].subscribes if t.startswith("result.")
    ]
    assert agents["reporter"].system_prompt == REPORTER_PROMPT
    assert "task.sinverguenza" in agents["reviewer"].publishes
    assert "publish_message" in agents["reviewer"].enabled_tools
    assert agents["reviewer"].system_prompt == REVIEWER_PROMPT
    assert agents["sinverguenza"].system_prompt == SINVERGUENZA_PROMPT
    assert set(agents["reviewer"].enabled_tools) >= {"run_nmap", "record_service"}
    assert agents["reviewer"].subscribes == ["discovery.ports.found", "human.reviewer"]
    assert agents["reviewer"].max_iterations == 20
    assert "record_service" not in agents["discoverer"].enabled_tools
    assert "report_open_ports" in agents["discoverer"].enabled_tools
    for name in NEW:
        assert {"result.reviewer", "result.discoverer"} <= set(agents[name].subscribes)


async def _legacy_install(databases) -> None:
    """Three agents and no security-agents flag: what an install from before this feature looks like."""
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        await session.execute(
            update(AiAgent)
            .where(AiAgent.name == "reporter")
            .values(subscribes=["task.reporter", "human.reporter"], system_prompt=LEGACY_REPORTER_PROMPT)
        )
        for name in NEW:
            await session.execute(AiAgent.__table__.delete().where(AiAgent.name == name))
        (await ensure_default_ai_mode_settings(session)).security_agents_seeded = False
        await session.commit()


async def test_existing_install_gets_the_agents_once(databases):
    await _legacy_install(databases)

    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
    agents = await _agents(databases)
    assert set(NEW) <= set(agents)
    assert agents["reporter"].subscribes == ["task.reporter", "human.reporter", *(f"result.{n}" for n in NEW)]
    assert agents["reporter"].system_prompt == REPORTER_PROMPT

    async with databases.app_session_factory() as session:
        await session.execute(AiAgent.__table__.delete().where(AiAgent.name == "sinverguenza"))
        await session.commit()
        await ensure_default_agents(session)
    assert "sinverguenza" not in await _agents(databases)  # deleting one is permanent


async def test_an_edited_reporter_prompt_is_kept(databases):
    await _legacy_install(databases)
    async with databases.app_session_factory() as session:
        await session.execute(
            update(AiAgent).where(AiAgent.name == "reporter").values(system_prompt="my prompt")
        )
        await session.commit()
        await ensure_default_agents(session)
    assert (await _agents(databases))["reporter"].system_prompt == "my prompt"


async def test_a_user_agent_with_a_security_name_is_left_alone(databases):
    await _legacy_install(databases)
    async with databases.app_session_factory() as session:
        session.add(AiAgent(name="bellaco", role="mine", enabled_tools=[]))
        await session.commit()
        await ensure_default_agents(session)
    assert (await _agents(databases))["bellaco"].role == "mine"


async def test_form_tool_is_backfilled_once_and_a_removed_copy_stays_removed(databases):
    """An install that predates submit_http_form (security_agents_seeded already True, so that seed path
    never re-runs) gets the tool added to the three stock security agents exactly once; removing it
    afterward stays removed, same guarantee as security_agents_seeded itself."""
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        for name in NEW:
            await session.execute(
                update(AiAgent)
                .where(AiAgent.name == name)
                .values(enabled_tools=["run_nc"])  # as if seeded before this tool existed
            )
        (await ensure_default_ai_mode_settings(session)).form_tool_seeded = False
        await session.commit()

    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
    agents = await _agents(databases)
    for name in NEW:
        assert agents[name].enabled_tools.count("submit_http_form") == 1

    async with databases.app_session_factory() as session:
        await session.execute(
            update(AiAgent).where(AiAgent.name == "bellaco").values(enabled_tools=["run_nc"])
        )
        await session.commit()
        await ensure_default_agents(session)  # a second call is a no-op: the flag is already True
    assert "submit_http_form" not in (await _agents(databases))["bellaco"].enabled_tools


async def _pre_escalation_install(databases) -> None:
    """A fresh install, then rewound to look like one that predates reviewer's escalation to
    sinverguenza: the old prompts/wiring restored and the flag cleared, so the backfill step runs."""
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        await session.execute(
            update(AiAgent)
            .where(AiAgent.name == "reviewer")
            .values(publishes=["result.#"], enabled_tools=["run_nc"], system_prompt=LEGACY_REVIEWER_PROMPT)
        )
        await session.execute(
            update(AiAgent)
            .where(AiAgent.name == "reporter")
            .values(
                subscribes=["task.reporter", "human.reporter", *(f"result.{n}" for n in NEW)],
                system_prompt=REPORTER_PROMPT_PRE_REVIEWER,
            )
        )
        (await ensure_default_ai_mode_settings(session)).reviewer_escalation_seeded = False
        await session.commit()


async def test_reviewer_escalation_is_backfilled_once(databases):
    await _pre_escalation_install(databases)

    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
    agents = await _agents(databases)

    assert "task.sinverguenza" in agents["reviewer"].publishes
    assert "publish_message" in agents["reviewer"].enabled_tools
    assert agents["reviewer"].system_prompt == REVIEWER_PROMPT
    assert "result.reviewer" in agents["reporter"].subscribes
    assert agents["reporter"].system_prompt == REPORTER_PROMPT

    async with databases.app_session_factory() as session:
        await session.execute(
            update(AiAgent).where(AiAgent.name == "reviewer").values(publishes=["result.#"])
        )
        await session.commit()
        await ensure_default_agents(session)  # a second call is a no-op: the flag is already True
    assert "task.sinverguenza" not in (await _agents(databases))["reviewer"].publishes


async def test_an_edited_reviewer_prompt_is_kept_during_backfill(databases):
    await _pre_escalation_install(databases)
    async with databases.app_session_factory() as session:
        await session.execute(
            update(AiAgent).where(AiAgent.name == "reviewer").values(system_prompt="my review prompt")
        )
        await session.commit()
        await ensure_default_agents(session)
    agents = await _agents(databases)
    assert agents["reviewer"].system_prompt == "my review prompt"
    assert "task.sinverguenza" in agents["reviewer"].publishes  # wiring still backfills independently


async def _pre_maestro_merge_install(databases) -> None:
    """A fresh install, then rewound to look like one that predates the maestro merge: sinverguenza
    still has its old prompt, a maestro agent exists again (as it would before retirement), reporter
    still subscribes to its result topic, and the flag is cleared so the backfill step runs."""
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        await session.execute(
            update(AiAgent)
            .where(AiAgent.name == "sinverguenza")
            .values(system_prompt=LEGACY_SINVERGUENZA_PROMPT)
        )
        session.add(
            AiAgent(
                name="maestro",
                role="Forensic analysis from integration data, optional VirusTotal checks",
                system_prompt="old maestro prompt",
                temperature=0.2,
                max_iterations=45,
                enabled_tools=["list_inspect_targets", "save_report"],
                subscribes=["task.maestro", "human.maestro"],
                publishes=["result.#"],
            )
        )
        await session.execute(
            update(AiAgent)
            .where(AiAgent.name == "reporter")
            .values(
                subscribes=[
                    "task.reporter", "human.reporter", "result.reviewer",
                    *(f"result.{n}" for n in NEW), "result.maestro",
                ],
                system_prompt=LEGACY_REPORTER_PROMPT_WITH_MAESTRO,
            )
        )
        (await ensure_default_ai_mode_settings(session)).maestro_merged_into_sinverguenza = False
        await session.commit()


async def test_maestro_is_merged_into_sinverguenza_once(databases):
    await _pre_maestro_merge_install(databases)

    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
    agents = await _agents(databases)

    assert "maestro" not in agents
    assert "result.maestro" not in agents["reporter"].subscribes
    assert agents["sinverguenza"].system_prompt == SINVERGUENZA_PROMPT
    assert agents["reporter"].system_prompt == REPORTER_PROMPT
    assert "result.maestro" not in agents["reporter"].system_prompt

    # a second call is a no-op: a maestro agent added back afterward is not touched or re-deleted
    async with databases.app_session_factory() as session:
        session.add(AiAgent(name="maestro", role="mine", enabled_tools=[]))
        await session.commit()
        await ensure_default_agents(session)
    assert "maestro" in await _agents(databases)


async def test_maestros_virustotal_permission_carries_over_to_sinverguenza(databases):
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        session.add(
            AiAgent(
                name="maestro",
                role="forensics",
                system_prompt="old",
                enabled_tools=["list_inspect_targets", "save_report", "virustotal_lookup"],
                subscribes=["task.maestro", "human.maestro"],
                publishes=["result.#"],
            )
        )
        (await ensure_default_ai_mode_settings(session)).maestro_merged_into_sinverguenza = False
        await session.commit()

    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
    assert "virustotal_lookup" in (await _agents(databases))["sinverguenza"].enabled_tools


async def test_maestro_without_virustotal_does_not_grant_it_to_sinverguenza(databases):
    await _pre_maestro_merge_install(databases)  # this maestro never had virustotal_lookup enabled
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
    assert "virustotal_lookup" not in (await _agents(databases))["sinverguenza"].enabled_tools


async def _pre_nmap_handoff_install(databases) -> None:
    """A fresh install, then rewound to look like one that predates reviewer taking over nmap-based
    service identification: the old stock tools/subscription/prompt/loop-limit restored and the flag
    cleared, so the backfill step runs."""
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        await session.execute(
            update(AiAgent)
            .where(AiAgent.name == "reviewer")
            .values(
                enabled_tools=["run_nc", "publish_message"],
                subscribes=["discovery.service.found", "human.reviewer"],
                system_prompt=LEGACY_REVIEWER_PROMPT_PRE_NMAP,
                max_iterations=6,
            )
        )
        (await ensure_default_ai_mode_settings(session)).reviewer_does_nmap_seeded = False
        await session.commit()


async def test_reviewer_nmap_handoff_is_backfilled_once(databases):
    await _pre_nmap_handoff_install(databases)

    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
    agents = await _agents(databases)

    assert set(agents["reviewer"].enabled_tools) == {
        "run_nc", "publish_message", "run_nmap", "record_service",
    }
    assert agents["reviewer"].subscribes == ["discovery.ports.found", "human.reviewer"]
    assert agents["reviewer"].system_prompt == REVIEWER_PROMPT
    assert agents["reviewer"].max_iterations == 20
    assert "report_open_ports" in agents["discoverer"].enabled_tools

    # a second call is a no-op: the flag is already True, so a tool removed afterward stays removed.
    async with databases.app_session_factory() as session:
        await session.execute(
            update(AiAgent).where(AiAgent.name == "reviewer").values(enabled_tools=["run_nc"])
        )
        await session.commit()
        await ensure_default_agents(session)
    assert (await _agents(databases))["reviewer"].enabled_tools == ["run_nc"]


async def test_an_edited_reviewer_prompt_is_kept_during_nmap_handoff(databases):
    await _pre_nmap_handoff_install(databases)
    async with databases.app_session_factory() as session:
        await session.execute(
            update(AiAgent).where(AiAgent.name == "reviewer").values(system_prompt="my review prompt")
        )
        await session.commit()
        await ensure_default_agents(session)
    agents = await _agents(databases)
    assert agents["reviewer"].system_prompt == "my review prompt"
    # every other field backfills independently of the prompt edit, same as the escalation backfill.
    assert set(agents["reviewer"].enabled_tools) >= {"run_nmap", "record_service"}
    assert agents["reviewer"].subscribes == ["discovery.ports.found", "human.reviewer"]
    assert agents["reviewer"].max_iterations == 20


async def test_discoverer_gets_report_open_ports_only_if_still_on_the_old_stock_tool_list(databases):
    await _pre_nmap_handoff_install(databases)
    async with databases.app_session_factory() as session:
        await session.execute(
            update(AiAgent)
            .where(AiAgent.name == "discoverer")
            .values(enabled_tools=["run_nmap", "run_nc", "record_service", "discover_hosts"])
        )
        await session.commit()
        await ensure_default_agents(session)
    assert (await _agents(databases))["discoverer"].enabled_tools == [
        "run_nmap", "run_nc", "record_service", "discover_hosts", "report_open_ports",
    ]

    # a customized list (anything not an exact match of the old stock default) is left alone.
    async with databases.app_session_factory() as session:
        await session.execute(
            update(AiAgent).where(AiAgent.name == "discoverer").values(enabled_tools=["record_service"])
        )
        (await ensure_default_ai_mode_settings(session)).reviewer_does_nmap_seeded = False
        await session.commit()
        await ensure_default_agents(session)
    assert (await _agents(databases))["discoverer"].enabled_tools == ["record_service"]


async def test_an_edited_reviewer_subscription_is_kept_during_nmap_handoff(databases):
    await _pre_nmap_handoff_install(databases)
    async with databases.app_session_factory() as session:
        await session.execute(
            update(AiAgent)
            .where(AiAgent.name == "reviewer")
            .values(subscribes=["discovery.service.found", "task.reviewer", "human.reviewer"])
        )
        await session.commit()
        await ensure_default_agents(session)
    agents = await _agents(databases)
    assert agents["reviewer"].subscribes == ["discovery.service.found", "task.reviewer", "human.reviewer"]
    # tool grants are purely additive and are not gated on the subscription edit.
    assert set(agents["reviewer"].enabled_tools) >= {"run_nmap", "record_service"}


async def test_an_edited_sinverguenza_prompt_is_kept_during_the_maestro_merge(databases):
    await _pre_maestro_merge_install(databases)
    async with databases.app_session_factory() as session:
        await session.execute(
            update(AiAgent)
            .where(AiAgent.name == "sinverguenza")
            .values(system_prompt="my sinverguenza prompt")
        )
        await session.commit()
        await ensure_default_agents(session)
    agents = await _agents(databases)
    assert agents["sinverguenza"].system_prompt == "my sinverguenza prompt"
    assert "maestro" not in agents  # deletion happens independently of the prompt backfill


async def test_an_edited_reporter_prompt_is_kept_during_the_maestro_merge(databases):
    await _pre_maestro_merge_install(databases)
    async with databases.app_session_factory() as session:
        await session.execute(
            update(AiAgent).where(AiAgent.name == "reporter").values(system_prompt="my reporter prompt")
        )
        await session.commit()
        await ensure_default_agents(session)
    agents = await _agents(databases)
    assert agents["reporter"].system_prompt == "my reporter prompt"
    assert "result.maestro" not in agents["reporter"].subscribes  # wiring still backfills independently


async def test_cross_agent_subscriptions_are_backfilled_once(databases):
    """An install from before bellaco/sinverguenza/reporter were wired to react to a plain
    discoverer/reviewer result gets those subscriptions added once, additively."""
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        for name in NEW:
            await session.execute(
                update(AiAgent)
                .where(AiAgent.name == name)
                .values(subscribes=[f"task.{name}", f"human.{name}"])
            )
        await session.execute(
            update(AiAgent)
            .where(AiAgent.name == "reporter")
            .values(
                subscribes=[
                    "task.reporter", "human.reporter", "result.reviewer", *(f"result.{n}" for n in NEW),
                ]
            )
        )
        (await ensure_default_ai_mode_settings(session)).cross_agent_subscriptions_seeded = False
        await session.commit()

    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
    agents = await _agents(databases)
    for name in NEW:
        assert {"result.reviewer", "result.discoverer"} <= set(agents[name].subscribes)
    assert "result.discoverer" in agents["reporter"].subscribes

    # a second call is a no-op: the flag is already True, so a subscription removed afterward stays removed.
    async with databases.app_session_factory() as session:
        await session.execute(
            update(AiAgent)
            .where(AiAgent.name == "bellaco")
            .values(subscribes=["task.bellaco", "human.bellaco"])
        )
        await session.commit()
        await ensure_default_agents(session)
    assert (await _agents(databases))["bellaco"].subscribes == ["task.bellaco", "human.bellaco"]


async def test_reviewer_escalates_a_bad_finding_to_sinverguenza(databases, monkeypatch):
    """Regression test for the reported bug: starting a run only ever ran discoverer/reviewer, and
    bellaco/sinverguenza/maestro/reporter stayed waiting forever because nothing was ever wired to
    reach them. Reviewer must now hand a non-"confirmed" finding to sinverguenza itself."""
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        keep = ("reviewer", "sinverguenza")
        await session.execute(update(AiAgent).where(AiAgent.name.not_in(keep)).values(enabled=False))
        await session.commit()
    prompts: list[str] = []

    async def fake(**kwargs):
        system = kwargs["messages"][0]["content"]
        user = kwargs["messages"][1]["content"]
        prompts.append(user)
        if "reviewer" in system:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "Escalated to sinverguenza.",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "publish_message",
                                        "arguments": json.dumps(
                                            {
                                                "topic": "task.sinverguenza",
                                                "content": "192.168.1.12:443 claims https but the banner "
                                                "doesn't look like TLS - please investigate",
                                            }
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"content": "Verdict: needs attention."}}]}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(
        databases,
        [],
        dry_run=False,
        entry_agent="reviewer",
        message="service found: 192.168.1.12:443 claims https",
    )
    await run_agent(databases, run_id)

    async with databases.app_session_factory() as session:
        messages = list(await session.scalars(select(AiMessage).where(AiMessage.run_id == run_id)))
        sinverguenza_steps = list(
            await session.scalars(
                select(AiRunStep).where(AiRunStep.run_id == run_id, AiRunStep.agent == "sinverguenza")
            )
        )
    assert "task.sinverguenza" in {m.topic for m in messages}
    assert sinverguenza_steps, "sinverguenza never ran"
    assert any("please investigate" in p for p in prompts)


async def test_a_finding_reaches_the_reporter(databases, monkeypatch):
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        keep = ("bellaco", "reporter")
        await session.execute(update(AiAgent).where(AiAgent.name.not_in(keep)).values(enabled=False))
        await session.commit()
    prompts: list[str] = []

    async def fake(**kwargs):
        system = kwargs["messages"][0]["content"]
        user = kwargs["messages"][1]["content"]
        prompts.append(user)
        if "agent 'bellaco'" in system:
            return {"choices": [{"message": {"content": "web1: warning, 12 packages upgradable"}}]}
        return {"choices": [{"message": {"content": "Report written."}}]}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(databases, [], dry_run=False, entry_agent="bellaco", message="check web1")
    await run_agent(databases, run_id)

    async with databases.app_session_factory() as session:
        messages = list(await session.scalars(select(AiMessage).where(AiMessage.run_id == run_id)))
        reporter_steps = list(
            await session.scalars(
                select(AiRunStep).where(AiRunStep.run_id == run_id, AiRunStep.agent == "reporter")
            )
        )
    assert "result.bellaco" in {m.topic for m in messages}
    assert reporter_steps, "the reporter handled nothing"
    assert any("12 packages upgradable" in p and "result.bellaco" in p for p in prompts)


async def test_reporter_saves_a_report_for_a_routine_reviewer_result(databases, monkeypatch):
    """Previously a plain, non-escalated reviewer result was just acknowledged with no save_report
    call; the rewritten reporter now condenses every agent-topic result into a real report."""
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
        keep = ("reviewer", "reporter")
        await session.execute(update(AiAgent).where(AiAgent.name.not_in(keep)).values(enabled=False))
        await session.commit()

    async def fake(**kwargs):
        system = kwargs["messages"][0]["content"]
        history = kwargs["messages"]
        if "agent 'reviewer'" in system:
            return {"choices": [{"message": {"content": "Identified: port 443 is https."}}]}
        if len(history) <= 2:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "1",
                                    "type": "function",
                                    "function": {
                                        "name": "save_report",
                                        "arguments": json.dumps(
                                            {"title": "Reviewer check", "content": "## Reviewer\nConfirmed."}
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"content": "Report saved."}}]}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(
        databases,
        [],
        dry_run=False,
        entry_agent="reviewer",
        message="service found: 192.168.1.12:443 claims https",
    )
    await run_agent(databases, run_id)

    async with databases.app_session_factory() as session:
        tool_steps = list(
            await session.scalars(
                select(AiRunStep).where(
                    AiRunStep.run_id == run_id, AiRunStep.agent == "reporter", AiRunStep.kind == "tool"
                )
            )
        )
    assert any(s.name == "save_report" for s in tool_steps)
