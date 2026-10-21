import asyncio
import datetime

import pytest
from sqlalchemy import select

from app.db.session import get_databases
from app.discovery.reachability import INACTIVE_AFTER
from app.domain.bootstrap import (
    ensure_default_agents,
    ensure_default_ai_mode_settings,
    ensure_default_discovery_settings,
)
from app.domain.enums import DeviceType, HealthStatus
from app.domain.models import AiRun, Base, Device, Network, Site, utcnow
from app.llm import schedule
from app.llm.agent import create_run
from app.llm.orchestrator import get_context, run_agent


@pytest.fixture
async def databases():
    dbs = get_databases()
    async with dbs.app_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with dbs.app_session_factory() as session:
        site = Site(name="s")
        session.add(site)
        await session.flush()
        for i in range(1, 6):
            session.add(
                Device(
                    site_id=site.id,
                    display_name=f"d{i}",
                    primary_ip=f"10.0.0.{i}",
                    device_type=DeviceType.OTHER,
                )
            )
        await ensure_default_agents(session)
        await session.commit()
    yield dbs
    await dbs.dispose()


async def _configure(databases, **values) -> None:
    async with databases.app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
        for key, value in values.items():
            setattr(settings, key, value)
        (await ensure_default_discovery_settings(session)).ai_mode_enabled = True
        await session.commit()


async def _assign_all_devices_to_a_network(databases) -> None:
    """next_targets only selects devices currently tied to a configured network - the fixture's five
    devices start out unassigned, so tests exercising target selection need one to exist."""
    async with databases.app_session_factory() as session:
        site = await session.scalar(select(Site))
        network = Network(site_id=site.id, name="LAN", cidr="10.0.0.0/24")
        session.add(network)
        await session.flush()
        await session.execute(Device.__table__.update().values(network_id=network.id))
        await session.commit()


def test_next_run_at() -> None:
    assert schedule.next_run_at(False, None, 60) is None
    last = utcnow()
    assert schedule.next_run_at(True, last, 60) == last + datetime.timedelta(seconds=60)
    assert schedule.next_run_at(True, None, 60) is not None  # never ran: due now


async def test_targets_rotate_through_every_device(databases) -> None:
    await _assign_all_devices_to_a_network(databases)
    first, cursor = await schedule.next_targets(databases, 0, 2)
    second, cursor = await schedule.next_targets(databases, cursor, 2)
    third, cursor = await schedule.next_targets(databases, cursor, 2)
    assert first == ["10.0.0.1", "10.0.0.2"] and second == ["10.0.0.3", "10.0.0.4"]
    assert third == ["10.0.0.5", "10.0.0.1"]  # wraps around, so nothing is skipped for long


async def test_devices_with_no_network_are_not_auto_selected(databases) -> None:
    """A device that was never assigned a network (the fixture's default) is excluded from
    automatic target selection, same as one whose network was deleted."""
    targets, _ = await schedule.next_targets(databases, 0, 10)
    assert targets == []


async def test_a_device_whose_network_was_deleted_drops_out_of_targets(databases) -> None:
    """Regression test: deleting a Network does not delete its Devices (they become unassigned,
    network_id None - see networks.py's delete_network), but a device no longer tied to any
    configured network should stop being scanned automatically along with the network it lost,
    instead of being targeted forever."""
    await _assign_all_devices_to_a_network(databases)
    async with databases.app_session_factory() as session:
        await session.execute(
            Device.__table__.update().where(Device.primary_ip == "10.0.0.3").values(network_id=None)
        )
        await session.commit()
    targets, _ = await schedule.next_targets(databases, 0, 10)
    assert targets == ["10.0.0.1", "10.0.0.2", "10.0.0.4", "10.0.0.5"]


async def test_an_inactive_device_drops_out_of_targets(databases) -> None:
    """A device down and unseen for longer than INACTIVE_AFTER is excluded - nothing keeps
    scanning/inspecting a host nothing has found in days - but a merely-down-for-a-moment one is
    still targeted (it may well answer this time)."""
    await _assign_all_devices_to_a_network(databases)
    long_ago = utcnow() - INACTIVE_AFTER - datetime.timedelta(seconds=1)
    async with databases.app_session_factory() as session:
        await session.execute(
            Device.__table__.update()
            .where(Device.primary_ip == "10.0.0.3")
            .values(status=HealthStatus.DOWN, last_seen_at=long_ago)
        )
        await session.execute(
            Device.__table__.update()
            .where(Device.primary_ip == "10.0.0.4")
            .values(status=HealthStatus.DOWN, last_seen_at=utcnow())
        )
        await session.commit()
    targets, _ = await schedule.next_targets(databases, 0, 10)
    assert targets == ["10.0.0.1", "10.0.0.2", "10.0.0.4", "10.0.0.5"]


async def test_scheduled_run_starts_only_when_due_and_idle(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[int] = []
    monkeypatch.setattr(schedule, "spawn_run", lambda dbs, run_id: started.append(run_id))
    await _assign_all_devices_to_a_network(databases)

    await _configure(databases, schedule_enabled=False, max_targets=3)
    await schedule.run_ai_schedule(databases)
    assert started == []  # schedule off

    await _configure(databases, schedule_enabled=True, schedule_interval_seconds=60)
    await schedule.run_ai_schedule(databases)
    assert len(started) == 1
    async with databases.app_session_factory() as session:
        run = await session.get(AiRun, started[0])
        settings = await ensure_default_ai_mode_settings(session)
    assert run.started_by == "schedule" and run.targets == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
    assert settings.schedule_cursor == 3 and settings.last_scheduled_at is not None

    await schedule.run_ai_schedule(databases)
    assert len(started) == 1  # the interval has not passed

    await _configure(databases, last_scheduled_at=utcnow() - datetime.timedelta(seconds=61))
    await schedule.run_ai_schedule(databases)
    assert len(started) == 1  # due, but the previous run is still marked running: never overlap

    async with databases.app_session_factory() as session:
        for run in (await session.scalars(select(AiRun))).all():
            run.status = "done"
        await session.commit()
    await schedule.run_ai_schedule(databases)
    assert len(started) == 2
    async with databases.app_session_factory() as session:
        second = await session.get(AiRun, started[1])
    assert second.targets == ["10.0.0.4", "10.0.0.5", "10.0.0.1"]


async def test_scheduled_run_with_no_devices_needs_a_network_and_finds_hosts_itself(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[int] = []
    monkeypatch.setattr(schedule, "spawn_run", lambda dbs, run_id: started.append(run_id))
    async with databases.app_session_factory() as session:
        for device in (await session.scalars(select(Device))).all():
            await session.delete(device)
        await session.commit()
    await _configure(databases, schedule_enabled=True, schedule_interval_seconds=60)

    await schedule.run_ai_schedule(databases)
    assert started == []  # nothing known and nothing configured

    async with databases.app_session_factory() as session:
        site = await session.scalar(select(Site))
        session.add(Network(site_id=site.id, name="LAN", cidr="10.0.0.0/24"))
        await session.commit()
    await schedule.run_ai_schedule(databases)
    assert len(started) == 1
    async with databases.app_session_factory() as session:
        assert (await session.get(AiRun, started[0])).targets == []


async def test_run_is_stopped_automatically_at_its_time_limit(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def slow(**kwargs: object) -> dict:
        await asyncio.sleep(30)
        return {}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", slow)
    run_id = await create_run(databases, ["10.0.0.1"], False)
    async with databases.app_session_factory() as session:
        run = await session.get(AiRun, run_id)
        assert run.settings_snapshot["max_run_seconds"] == 30 * 60  # default from settings
        run.settings_snapshot = {**run.settings_snapshot, "max_run_seconds": 0.3}
        await session.commit()

    await asyncio.wait_for(run_agent(databases, run_id), 5)

    async with databases.app_session_factory() as session:
        run = await session.get(AiRun, run_id)
    assert run.status == "done" and run.stop_reason == "time_limit"
    assert "time limit" in run.summary


async def test_run_can_be_stopped_by_hand_and_reports_agent_states(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def slow(**kwargs: object) -> dict:
        await asyncio.sleep(30)
        return {}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", slow)
    run_id = await create_run(databases, ["10.0.0.1"], False)
    task = asyncio.create_task(run_agent(databases, run_id))
    for _ in range(100):
        context = get_context(run_id)
        if context is not None and context.agent_state.get("discoverer") == "llm":
            break
        await asyncio.sleep(0.02)
    assert context is not None
    assert context.agent_state == {
        "discoverer": "llm",
        **{n: "waiting" for n in ("reviewer", "reporter", "bellaco", "sinverguenza", "tajonaso")},
    }
    assert context.deadline > context.started_at

    context.stop()
    await asyncio.wait_for(task, 5)

    async with databases.app_session_factory() as session:
        run = await session.get(AiRun, run_id)
    assert run.status == "done" and run.stop_reason == "manual" and run.summary == "Stopped by a human."
    assert get_context(run_id) is None


async def _wait_for(predicate, timeout: float = 3.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached")


async def test_stopping_one_agent_drops_its_queue_and_the_rest_carry_on(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.models import AiMessageDelivery
    from app.llm.bus import get_message_bus
    from app.llm.orchestrator import start_agent, stop_agent

    discoverer_busy = False

    async def fake(**kwargs: object) -> dict:
        system = kwargs["messages"][0]["content"]  # type: ignore[index]
        if "agent 'reviewer'" in system or ("agent 'discoverer'" in system and discoverer_busy):
            await asyncio.sleep(30)  # slow, so a second message queues behind the first
        return {"choices": [{"message": {"content": "ok", "reasoning": None}}]}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(databases, ["10.0.0.1"], False)
    task = asyncio.create_task(run_agent(databases, run_id))
    await _wait_for(lambda: get_context(run_id) is not None and "reviewer" in get_context(run_id).workers)
    ctx = get_context(run_id)
    bus = get_message_bus()

    discoverer_busy = True  # keeps the run alive while the reviewer is stopped and started
    await bus.publish(run_id, "human.discoverer", "human", {"text": "stay busy"})
    await bus.publish(run_id, "human.reviewer", "human", {"text": "first"})
    await bus.publish(run_id, "human.reviewer", "human", {"text": "second"})
    await _wait_for(lambda: ctx.agent_state.get("reviewer") == "llm")

    await stop_agent(ctx, "reviewer")

    assert "reviewer" in ctx.stopped_agents and "reviewer" not in ctx.workers
    async with databases.app_session_factory() as session:
        deliveries = await session.scalars(
            select(AiMessageDelivery).where(AiMessageDelivery.recipient == "reviewer")
        )
        states = {d.state for d in deliveries}
    assert states == {"acked", "dropped"}  # the one being handled was cancelled; the queued one was dropped

    late = await bus.publish(run_id, "human.reviewer", "human", {"text": "nobody home"})
    assert late.recipients == []  # a stopped agent is no longer a subscriber

    start_agent(ctx, "reviewer")
    again = await bus.publish(run_id, "human.reviewer", "human", {"text": "back"})
    assert again.recipients == ["reviewer"]

    await stop_agent(ctx, "reviewer")
    ctx.stop()
    await asyncio.wait_for(task, 5)


async def test_stopping_an_agent_rejects_what_it_had_parked_for_approval(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import update

    from app.domain.models import AiAgent, AiMessage
    from app.llm.orchestrator import stop_agent

    async with databases.app_session_factory() as session:
        await session.execute(update(AiAgent).where(AiAgent.name == "reviewer").values(enabled=False))
        await session.execute(
            update(AiAgent).where(AiAgent.name == "discoverer").values(require_approval="messages")
        )
        await session.commit()

    async def fake(**kwargs: object) -> dict:
        return {"choices": [{"message": {"content": "all done", "reasoning": None}}]}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(databases, ["10.0.0.1"], False)
    task = asyncio.create_task(run_agent(databases, run_id))

    async def held_count() -> int:
        async with databases.app_session_factory() as session:
            return len((await session.scalars(select(AiMessage).where(AiMessage.status == "held"))).all())

    for _ in range(100):
        if await held_count():
            break
        await asyncio.sleep(0.02)
    ctx = get_context(run_id)
    await stop_agent(ctx, "discoverer")

    await asyncio.wait_for(task, 5)  # the parked message no longer keeps the run alive
    async with databases.app_session_factory() as session:
        message = await session.scalar(select(AiMessage).where(AiMessage.topic == "result.discoverer"))
    assert message.status == "rejected" and message.note == "the agent was stopped"


async def test_run_snapshot_lists_every_network_including_empty_ones(databases) -> None:
    from app.domain.models import Network

    async with databases.app_session_factory() as session:
        site_id = (await session.scalar(select(Site.id)))
        session.add_all(
            [
                Network(site_id=site_id, name="lan", cidr="10.0.0.0/24"),
                Network(site_id=site_id, name="iot", cidr="10.0.1.0/24"),
            ]
        )
        await session.flush()
        lan = await session.scalar(select(Network.id).where(Network.name == "lan"))
        device = await session.scalar(select(Device).limit(1))
        device.network_id = lan
        await session.commit()

    run_id = await create_run(databases, ["10.0.0.1"], False)
    async with databases.app_session_factory() as session:
        run = await session.get(AiRun, run_id)
    assert run.settings_snapshot["networks"] == [
        {"name": "lan", "cidr": "10.0.0.0/24", "devices": 1},
        {"name": "iot", "cidr": "10.0.1.0/24", "devices": 0},
    ]


async def test_interval_counts_from_when_the_last_scheduled_run_finished(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[int] = []
    monkeypatch.setattr(schedule, "spawn_run", lambda dbs, run_id: started.append(run_id))
    await _assign_all_devices_to_a_network(databases)
    await _configure(databases, schedule_enabled=True, schedule_interval_seconds=60)
    await schedule.run_ai_schedule(databases)
    assert len(started) == 1

    async with databases.app_session_factory() as session:
        settings = await ensure_default_ai_mode_settings(session)
        settings.last_scheduled_at = utcnow() - datetime.timedelta(seconds=300)
        run = await session.get(AiRun, started[0])
        run.status = "done"
        run.finished_at = utcnow() - datetime.timedelta(seconds=10)  # a long run: started long ago
        await session.commit()
    await schedule.run_ai_schedule(databases)
    assert len(started) == 1  # only 10s since it finished, the 60s pause has not passed

    async with databases.app_session_factory() as session:
        run = await session.get(AiRun, started[0])
        run.finished_at = utcnow() - datetime.timedelta(seconds=61)
        await session.commit()
    await schedule.run_ai_schedule(databases)
    assert len(started) == 2
