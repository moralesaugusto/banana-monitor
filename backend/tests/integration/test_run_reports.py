"""Findings and per-network run reports: record_finding, the report built from it, the Markdown download."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import get_databases
from app.domain.models import AiRun, HostFinding
from app.llm.agent_tools import AgentToolError, dispatch
from app.reports.run_report import collect_scopes, save_run_reports


async def _network(client: AsyncClient, name: str, cidr: str) -> int:
    return (await client.post("/api/networks", json={"name": name, "cidr": cidr})).json()["id"]


async def _device(client: AsyncClient, name: str, ip: str, network_id: int | None) -> None:
    await client.post(
        "/api/devices",
        json={"display_name": name, "device_type": "linux", "primary_ip": ip, "network_id": network_id},
    )


async def _run(databases, targets: list[str]) -> int:
    async with databases.app_session_factory() as session:
        run = AiRun(targets=targets, settings_snapshot={})
        session.add(run)
        await session.commit()
        return run.id


async def _finding(databases, run_id: int, ip: str, kind: str, title: str, severity: str = "info") -> None:
    await dispatch(
        databases,
        "record_finding",
        {"ip": ip, "kind": kind, "title": title, "severity": severity, "detail": f"{title} detail"},
        agent_name="bellaco",
        run_id=run_id,
    )


@pytest.mark.asyncio
async def test_record_finding_validates_and_updates_in_place(client: AsyncClient) -> None:
    databases = get_databases()
    await _device(client, "web1", "10.0.0.5", await _network(client, "Lab", "10.0.0.0/24"))
    run_id = await _run(databases, [])
    await _finding(databases, run_id, "10.0.0.5", "patch", "14 pending updates", "medium")
    await _finding(databases, run_id, "10.0.0.5", "patch", "14 pending updates", "high")

    async with databases.app_session_factory() as session:
        rows = list(await session.scalars(select(HostFinding)))
    assert len(rows) == 1 and rows[0].severity == "high" and rows[0].device_id is not None

    with pytest.raises(AgentToolError):
        await dispatch(databases, "record_finding", {"ip": "10.0.0.5", "kind": "nonsense", "title": "x"})
    dry = await dispatch(
        databases, "record_finding", {"ip": "10.0.0.5", "kind": "os", "title": "x"}, dry_run=True
    )
    assert dry["dry_run"] is True


@pytest.mark.asyncio
async def test_each_network_gets_a_report_and_several_get_a_roll_up(client: AsyncClient) -> None:
    databases = get_databases()
    lab = await _network(client, "Lab", "10.0.0.0/24")
    dmz = await _network(client, "DMZ", "10.0.1.0/24")
    await _device(client, "web1", "10.0.0.5", lab)
    await _device(client, "db1", "10.0.0.6", lab)
    await _device(client, "proxy", "10.0.1.5", dmz)
    run_id = await _run(databases, [])
    await _finding(databases, run_id, "10.0.0.5", "os", "Debian 12.5")
    await _finding(databases, run_id, "10.0.0.5", "patch", "3 pending security updates", "medium")
    await _finding(databases, run_id, "10.0.1.5", "vulnerability", "SSH allows root login", "critical")

    scopes = await collect_scopes(databases, run_id)
    ids = await save_run_reports(databases, run_id, scopes, "Fix the proxy first.", ["Agent error: boom"])
    assert len(ids) == 3

    reports = {r["scope"]: r for r in (await client.get("/api/reports")).json()}
    assert set(reports) == {"Lab", "DMZ", "All networks"}
    lab_md = (await client.get(f"/api/reports/{reports['Lab']['id']}")).json()["content"]
    assert "Debian 12.5" in lab_md and "3 pending security updates" in lab_md
    assert "SSH allows root login" not in lab_md and "proxy" not in lab_md
    assert "db1" in lab_md.split("Not assessed")[1], "a host nobody assessed is named, not omitted"
    assert "Fix the proxy first." not in lab_md, "the narrative belongs to the roll-up when there are several"
    assert "Agent error: boom" in lab_md
    all_md = (await client.get(f"/api/reports/{reports['All networks']['id']}")).json()["content"]
    assert "Fix the proxy first." in all_md and "SSH allows root login" in all_md
    assert "Debian 12.5" not in all_md.split("Critical and high findings")[1]
    assert "| DMZ | 1 | 0 | 0 | 0 | 1 | critical |" in all_md
    assert "| Lab | 2 | 0 | 0 | 0 | 2 | medium |" in all_md


@pytest.mark.asyncio
async def test_explicit_targets_limit_the_report_to_those_hosts(client: AsyncClient) -> None:
    databases = get_databases()
    lab = await _network(client, "Lab", "10.0.0.0/24")
    await _device(client, "web1", "10.0.0.5", lab)
    await _device(client, "db1", "10.0.0.6", lab)
    run_id = await _run(databases, ["10.0.0.5"])

    (scope,) = await collect_scopes(databases, run_id)
    assert [d["name"] for d in scope.snapshot["devices"]] == ["web1"]


@pytest.mark.asyncio
async def test_a_second_run_report_shows_what_changed(client: AsyncClient) -> None:
    databases = get_databases()
    lab = await _network(client, "Lab", "10.0.0.0/24")
    await _device(client, "web1", "10.0.0.5", lab)
    first = await _run(databases, [])
    await save_run_reports(databases, first, await collect_scopes(databases, first), None, [])

    second = await _run(databases, [])
    await _finding(databases, second, "10.0.0.5", "vulnerability", "Telnet open", "high")
    ids = await save_run_reports(databases, second, await collect_scopes(databases, second), None, [])

    content = (await client.get(f"/api/reports/{ids[0]}")).json()["content"]
    assert "No earlier report" not in content
    assert "New high finding on web1: Telnet open" in content


@pytest.mark.asyncio
async def test_markdown_and_pdf_downloads(client: AsyncClient) -> None:
    databases = get_databases()
    lab = await _network(client, "Lab", "10.0.0.0/24")
    await _device(client, "web1", "10.0.0.5", lab)
    run_id = await _run(databases, [])
    await _finding(databases, run_id, "10.0.0.5", "os", "Debian 12.5")
    (report_id,) = await save_run_reports(
        databases, run_id, await collect_scopes(databases, run_id), None, []
    )

    markdown = await client.get(f"/api/reports/{report_id}/markdown")
    assert markdown.status_code == 200 and markdown.headers["content-type"].startswith("text/markdown")
    assert markdown.text.startswith("# Lab report") and "Debian 12.5" in markdown.text
    assert (await client.get(f"/api/reports/{report_id}/pdf")).content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_snapshot_report_includes_os_and_findings(client: AsyncClient) -> None:
    databases = get_databases()
    await _device(client, "web1", "10.0.0.5", await _network(client, "Lab", "10.0.0.0/24"))
    run_id = await _run(databases, [])
    await _finding(databases, run_id, "10.0.0.5", "os", "Debian 12.5")
    await _finding(databases, run_id, "10.0.0.5", "incident", "Unknown SSH key", "high")

    content = (await client.post("/api/reports/snapshot")).json()["content"]
    assert "Debian 12.5" in content and "Unknown SSH key" in content


@pytest.mark.asyncio
async def test_a_narratives_own_headings_stay_below_the_reports_sections(client: AsyncClient) -> None:
    databases = get_databases()
    await _device(client, "web1", "10.0.0.5", await _network(client, "Lab", "10.0.0.0/24"))
    run_id = await _run(databases, [])
    (report_id,) = await save_run_reports(
        databases, run_id, await collect_scopes(databases, run_id), "# Title\n## Summary\ntext", []
    )

    content = (await client.get(f"/api/reports/{report_id}")).json()["content"]
    assert "### Title" in content and "### Summary" in content and "\n# Title" not in content
