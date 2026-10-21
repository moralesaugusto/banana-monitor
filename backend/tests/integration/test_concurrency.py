"""Regression tests for the races and scheduler collisions found in the concurrency audit."""

import asyncio
from typing import ClassVar

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.alerting import engine as alert_engine
from app.alerting.engine import get_alert_engine
from app.db.session import get_databases
from app.discovery import network_scanner, reachability
from app.discovery.service import DiscoveredServiceStore, DiscoveryService
from app.domain.enums import AlertConditionType, DeviceType, EntityType
from app.domain.models import (
    AiRun,
    AlertEvent,
    AlertRule,
    AlertStateRow,
    Device,
    Integration,
    IntegrationTarget,
    Service,
)
from app.integrations import registry
from app.integrations.base import PollResult, TargetDescriptor, ValidationResult
from app.llm import schedule
from app.metrics.writer import MetricsWriter
from app.scheduler.supervisor import PollingSupervisor

# --- 1. only one AI run can start, whoever asks ---------------------------------------------------


async def _enable_ai_with_a_device(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    await client.put("/api/ai-mode/settings", json={"enabled": True})
    network = (await client.post("/api/networks", json={"name": "lan", "cidr": "10.0.0.0/24"})).json()
    device = {
        "display_name": "d", "device_type": "other", "primary_ip": "10.0.0.5", "network_id": network["id"],
    }
    await client.post("/api/devices", json=device)

    async def slow(**kwargs: object) -> dict:
        await asyncio.sleep(30)
        return {}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", slow)


async def test_simultaneous_starts_create_exactly_one_run(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _enable_ai_with_a_device(client, monkeypatch)
    results = await asyncio.gather(*(client.post("/api/ai-mode/runs", json={}) for _ in range(4)))
    assert sorted(r.status_code for r in results) == [202, 409, 409, 409]
    async with get_databases().app_session_factory() as session:
        assert len((await session.scalars(select(AiRun))).all()) == 1


async def test_the_scheduler_and_a_manual_start_cannot_both_start_a_run(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _enable_ai_with_a_device(client, monkeypatch)
    await client.put(
        "/api/ai-mode/schedule", json={"schedule_enabled": True, "schedule_interval_seconds": 300}
    )
    manual, _ = await asyncio.gather(
        client.post("/api/ai-mode/runs", json={}), schedule.run_ai_schedule(get_databases())
    )
    async with get_databases().app_session_factory() as session:
        assert len((await session.scalars(select(AiRun))).all()) == 1
    assert manual.status_code in (202, 409)


# --- 2. two triggers, one scan --------------------------------------------------------------------


async def test_two_simultaneous_scans_of_a_network_run_once(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    network = (await client.post("/api/networks", json={"name": "n", "cidr": "10.9.0.0/30"})).json()
    arp_reads = 0

    async def slow_arp() -> dict[str, str]:
        nonlocal arp_reads
        arp_reads += 1
        await asyncio.sleep(0.2)
        return {}

    async def no_ping(*a: object, **k: object) -> bool:
        return False

    async def no_ports(*a: object, **k: object) -> list[int]:
        return []

    monkeypatch.setattr(network_scanner.arp, "get_arp_table", slow_arp)
    monkeypatch.setattr(network_scanner.icmp, "ping_host", no_ping)
    monkeypatch.setattr(network_scanner.tcp_ports, "scan_ports", no_ports)

    await asyncio.gather(*(network_scanner.scan_network(get_databases(), network["id"]) for _ in range(3)))
    assert arp_reads == 1
    await network_scanner.scan_network(get_databases(), network["id"])  # and it can be scanned again later
    assert arp_reads == 2


# --- 3 and 4. alert evaluation and the poll loops -------------------------------------------------


async def test_concurrent_alert_evaluations_create_one_state_and_one_event(client: AsyncClient) -> None:
    databases = get_databases()
    async with databases.app_session_factory() as session:
        session.add(
            AlertRule(
                name="r",
                condition_type=AlertConditionType.SERVICE_DOWN,
                entity_selector={},
                parameters={"for_duration_seconds": 0, "staleness_seconds": 1},
            )
        )
        await session.commit()
    outcomes = await asyncio.gather(
        *(get_alert_engine().evaluate_entity(EntityType.SERVICE, 1) for _ in range(5)),
        return_exceptions=True,
    )
    assert not [o for o in outcomes if isinstance(o, Exception)]
    async with databases.app_session_factory() as session:
        assert len((await session.scalars(select(AlertStateRow))).all()) == 1
        events = (await session.scalars(select(AlertEvent).order_by(AlertEvent.id))).all()
    # Evaluated one after another, the state walks OK -> pending -> firing exactly once each; a race
    # would record the same transition twice.
    transitions = [(e.from_state, e.to_state) for e in events]
    assert len(transitions) == len(set(transitions))


async def test_a_failed_poll_iteration_does_not_end_monitoring(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    databases = get_databases()
    async with databases.app_session_factory() as session:
        service = Service(
            name="s", service_type="tcp", config={"host": "127.0.0.1", "port": 1, "interval_seconds": 0.2}
        )
        session.add(service)
        await session.commit()
        await session.refresh(service)
    calls = 0

    async def flaky(self: object, entity_type: object, entity_id: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise IntegrityError("insert", {}, Exception("UNIQUE constraint failed"))

    monkeypatch.setattr(alert_engine.AlertEngine, "evaluate_entity", flaky)
    monkeypatch.setattr("app.scheduler.supervisor.random.uniform", lambda a, b: 0)
    supervisor = PollingSupervisor(databases, MetricsWriter(databases))
    supervisor._running = True
    supervisor.add_target(service)
    await asyncio.sleep(1.2)
    task = supervisor._service_tasks[service.id]
    assert not task.done() and calls >= 2  # it kept polling after the error
    task.cancel()


# --- 5. an integration is started once ------------------------------------------------------------


class SlowListing:
    type_key: ClassVar[str] = "slow_listing"
    display_name: ClassVar[str] = "slow"
    config_schema: ClassVar[dict] = {}
    credential_types: ClassVar[list] = []

    async def validate_config(self, config: dict, credential: dict | None) -> ValidationResult:
        return ValidationResult(ok=True)

    async def list_targets(self, config: dict, credential: dict | None) -> list[TargetDescriptor]:
        await asyncio.sleep(0.2)
        return [TargetDescriptor(external_ref="t", display_name="t", device_id=1)]

    async def discover(self, *args: object, **kwargs: object) -> list:
        return []

    async def poll(self, config: dict, credential: dict | None, target: TargetDescriptor) -> PollResult:
        return PollResult(success=True)


def _pollers() -> list[asyncio.Task]:
    return [t for t in asyncio.all_tasks() if "_run_integration_target" in repr(t.get_coro())]


@pytest.fixture
async def slow_integration(client: AsyncClient):
    registry.register(SlowListing())
    async with get_databases().app_session_factory() as session:
        integration = Integration(integration_type="slow_listing", name="s", config={"interval_seconds": 60})
        session.add(integration)
        await session.commit()
        await session.refresh(integration)
    supervisor = PollingSupervisor(get_databases(), MetricsWriter(get_databases()))
    supervisor._running = True
    yield supervisor, integration
    await supervisor.stop()
    registry._REGISTRY.pop("slow_listing", None)


async def test_starting_an_integration_twice_starts_one_set_of_pollers(slow_integration) -> None:
    supervisor, integration = slow_integration
    await asyncio.gather(supervisor.add_integration(integration), supervisor.add_integration(integration))
    assert len(_pollers()) == 1 and len(supervisor._integration_tasks[integration.id]) == 1


async def test_reload_during_startup_leaves_one_set_of_pollers(slow_integration) -> None:
    supervisor, integration = slow_integration
    await asyncio.gather(supervisor.add_integration(integration), supervisor.reload_integration(integration))
    assert len(_pollers()) == 1


async def test_removing_an_integration_while_it_starts_leaks_nothing(slow_integration) -> None:
    supervisor, integration = slow_integration
    starting = asyncio.create_task(supervisor.add_integration(integration))
    await asyncio.sleep(0.05)
    supervisor.remove_integration(integration.id)
    await starting
    await asyncio.sleep(0)
    assert not [t for t in _pollers() if not t.cancelled() and not t.done()]
    assert integration.id not in supervisor._integration_tasks


# --- 6. one service per (device, port) ------------------------------------------------------------


async def test_concurrent_upserts_create_one_service(client: AsyncClient) -> None:
    databases = get_databases()
    device = await DiscoveryService(databases).record_device_observation(
        network_id=None, ip="10.0.0.6", mac=None, hostname=None, open_ports=[], via="t"
    )
    store = DiscoveredServiceStore(databases)
    await asyncio.gather(
        *(
            store.upsert(device_id=device, ip="10.0.0.6", port=22, service_type="tcp", source=source)
            for source in ("scan", "ai", "scan", "scan")
        )
    )
    async with databases.app_session_factory() as session:
        assert len((await session.scalars(select(Service).where(Service.port == 22))).all()) == 1


async def test_startup_reconcile_folds_existing_scan_duplicates(client: AsyncClient) -> None:
    databases = get_databases()
    device = await DiscoveryService(databases).record_device_observation(
        network_id=None, ip="10.0.0.6", mac=None, hostname=None, open_ports=[], via="t"
    )
    async with databases.app_session_factory() as session:
        for fingerprint in (None, {"product": "OpenSSH", "source": "nmap"}, None):
            session.add(
                Service(
                    device_id=device,
                    name="ssh",
                    service_type="tcp",
                    config={},
                    port=22,
                    managed=False,
                    source="scan",
                    fingerprint=fingerprint,
                )
            )
        await session.commit()
    await DiscoveredServiceStore(databases).reconcile()
    async with databases.app_session_factory() as session:
        rows = (await session.scalars(select(Service).where(Service.port == 22))).all()
    assert len(rows) == 1 and rows[0].fingerprint == {"product": "OpenSSH", "source": "nmap"}


# --- 7. the metrics writer survives a locked database ---------------------------------------------


async def test_metrics_writer_keeps_running_and_retries_after_a_locked_database(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.metrics_models import CheckResult

    databases = get_databases()
    writer = MetricsWriter(databases, flush_interval=0.05)
    real_factory = databases.metrics_session_factory
    failures = {"left": 2}

    def locked_then_ok() -> object:
        if failures["left"] > 0:
            failures["left"] -= 1
            raise OperationalError("commit", {}, Exception("database is locked"))
        return real_factory()

    monkeypatch.setattr(databases, "metrics_session_factory", locked_then_ok)
    writer.enqueue_check_result(entity_type=EntityType.SERVICE, entity_id=1, success=True)
    await writer.start()
    await asyncio.sleep(0.6)
    assert writer._task is not None and not writer._task.done()  # still alive
    await writer.stop()
    async with real_factory() as session:
        assert len((await session.scalars(select(CheckResult))).all()) == 1  # and nothing was lost


# --- 8. an agent survives an unexpected error -------------------------------------------------------


async def test_an_agent_that_hits_an_unexpected_error_keeps_handling_messages(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.bootstrap import ensure_default_agents
    from app.llm.agent import create_run
    from app.llm.bus import get_message_bus
    from app.llm.orchestrator import get_context, run_agent

    databases = get_databases()
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
    handled: list[str] = []

    async def fake(**kwargs: object) -> dict:
        system = kwargs["messages"][0]["content"]  # type: ignore[index]
        if "agent 'reviewer'" in system:
            user = kwargs["messages"][1]["content"]  # type: ignore[index]
            handled.append(user)
            if "boom" in user:
                raise OSError("disk I/O error")  # not an LLM error: nothing used to catch this
        return {"choices": [{"message": {"content": "ok", "reasoning": None}}]}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(databases, ["10.0.0.1"], False)
    task = asyncio.create_task(run_agent(databases, run_id))
    for _ in range(100):
        ctx = get_context(run_id)
        if ctx and "reviewer" in ctx.workers:
            break
        await asyncio.sleep(0.02)
    bus = get_message_bus()
    # Both are queued before the first is handled; the second is handled only if the worker survives.
    await bus.publish(run_id, "human.reviewer", "human", {"text": "boom"})
    await bus.publish(run_id, "human.reviewer", "human", {"text": "after"})
    await asyncio.wait_for(task, 10)

    assert any("after" in m for m in handled)  # the next message was handled
    async with databases.app_session_factory() as session:
        run = await session.get(AiRun, run_id)
    assert run.status == "error" and "disk I/O error" in run.error  # and the failure is reported, not hidden


# --- 8b. per-provider LLM call concurrency gates --------------------------------------------------


async def test_ollama_concurrency_cap_bounds_in_flight_model_calls(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.bootstrap import ensure_default_agents
    from app.llm.agent import create_run
    from app.llm.bus import get_message_bus
    from app.llm.orchestrator import get_context, run_agent

    databases = get_databases()
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
    await client.put("/api/ai-mode/settings", json={"ollama_max_concurrent_calls": 2})

    lock = asyncio.Lock()
    in_flight = 0
    peak = 0

    async def fake(**kwargs: object) -> dict:
        nonlocal in_flight, peak
        async with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        async with lock:
            in_flight -= 1
        return {"choices": [{"message": {"content": "ok", "reasoning": None}}]}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(databases, ["10.0.0.1"], False)
    task = asyncio.create_task(run_agent(databases, run_id))
    targets = ["reviewer", "bellaco", "sinverguenza"]
    for _ in range(200):
        ctx = get_context(run_id)
        if ctx and all(name in ctx.workers for name in targets):
            break
        await asyncio.sleep(0.01)
    bus = get_message_bus()
    await asyncio.gather(*(bus.publish(run_id, f"human.{name}", "human", {"text": "go"}) for name in targets))
    await asyncio.wait_for(task, 10)

    assert peak <= 2


async def test_ollama_and_openrouter_concurrency_gates_are_independent(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.bootstrap import ensure_default_agents
    from app.llm.agent import create_run
    from app.llm.bus import get_message_bus
    from app.llm.orchestrator import get_context, run_agent

    databases = get_databases()
    async with databases.app_session_factory() as session:
        await ensure_default_agents(session)
    await client.put("/api/ai-mode/settings", json={"ollama_max_concurrent_calls": 1})
    agents_resp = await client.get("/api/ai-mode/agents")
    for row in agents_resp.json():
        if row["name"] in ("bellaco", "sinverguenza"):
            await client.put(
                f"/api/ai-mode/agents/{row['id']}",
                json={**row, "provider": "openrouter", "model_override": "a-model"},
            )

    lock = asyncio.Lock()
    in_flight: dict[str, int] = {"ollama": 0, "openrouter": 0}
    peak: dict[str, int] = {"ollama": 0, "openrouter": 0}

    async def fake(**kwargs: object) -> dict:
        provider = "openrouter" if "openrouter" in str(kwargs.get("base_url", "")) else "ollama"
        async with lock:
            in_flight[provider] += 1
            peak[provider] = max(peak[provider], in_flight[provider])
        await asyncio.sleep(0.05)
        async with lock:
            in_flight[provider] -= 1
        return {"choices": [{"message": {"content": "ok", "reasoning": None}}]}

    monkeypatch.setattr("app.llm.orchestrator.call_chat_completions", fake)
    run_id = await create_run(databases, ["10.0.0.1"], False)
    task = asyncio.create_task(run_agent(databases, run_id))
    targets = ["reviewer", "bellaco", "sinverguenza"]
    for _ in range(200):
        ctx = get_context(run_id)
        if ctx and all(name in ctx.workers for name in targets):
            break
        await asyncio.sleep(0.01)
    bus = get_message_bus()
    await asyncio.gather(*(bus.publish(run_id, f"human.{name}", "human", {"text": "go"}) for name in targets))
    await asyncio.wait_for(task, 10)

    assert peak["ollama"] <= 1
    assert peak["openrouter"] <= 2  # bellaco and sinverguenza could both be in flight at once


# --- 9. ping and an integration do not both write a device's status --------------------------------


async def test_reachability_leaves_integration_polled_devices_alone(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    databases = get_databases()
    async with databases.app_session_factory() as session:
        plain = Device(site_id=1, display_name="plain", primary_ip="10.0.1.1", device_type=DeviceType.OTHER)
        targeted = Device(
            site_id=1, display_name="targeted", primary_ip="10.0.1.2", device_type=DeviceType.OTHER
        )
        configured = Device(
            site_id=1, display_name="configured", primary_ip="10.0.1.3", device_type=DeviceType.OTHER
        )
        session.add_all([plain, targeted, configured])
        await session.flush()
        integration = Integration(integration_type="proxmox", name="p", config={})
        ssh = Integration(integration_type="generic_ssh", name="s", config={"device_id": configured.id})
        session.add_all([integration, ssh])
        await session.flush()
        session.add(
            IntegrationTarget(integration_id=integration.id, device_id=targeted.id, external_ref="vm1")
        )
        await session.commit()

    probed: list[str] = []

    async def fake_probe(ip: str, ports: list[int]) -> object:
        probed.append(ip)
        from app.domain.enums import HealthStatus

        return HealthStatus.UP

    monkeypatch.setattr(reachability, "probe_device", fake_probe)
    await reachability.run_reachability(databases)
    assert probed == ["10.0.1.1"]
