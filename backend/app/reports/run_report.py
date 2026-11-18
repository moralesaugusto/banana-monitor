"""Reports assembled when an AI Mode run ends: one per network the run touched, plus an 'All networks'
roll-up when it touched more than one. Built from the database (devices, services and the structured
findings agents recorded), so every host is in the report whatever order the agents finished in and
without a model. The reporter agent only contributes a short narrative on top (`narrative`)."""

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.db.session import Databases
from app.domain.enums import HealthStatus
from app.domain.models import AiRun, HostFinding, Report, utcnow
from app.reports.builder import (
    SEVERITY_RANK,
    _cell,
    _worst_severity,
    build_snapshot,
    compute_delta,
    delta_markdown,
    snapshot_markdown,
)
from app.telegram.bot import notify_report_saved

ALL_NETWORKS = "All networks"
UNASSIGNED = "Unassigned"


@dataclass
class Scope:
    name: str
    snapshot: dict[str, Any]


def _counts(items: list[str]) -> dict[str, int]:
    return {s.value: sum(1 for i in items if i == s.value) for s in HealthStatus}


def _scoped(
    snapshot: dict[str, Any], devices: list[dict[str, Any]], networks: list[dict[str, Any]]
) -> dict[str, Any]:
    names = {d["name"] for d in devices}
    return {
        **snapshot,
        "networks": networks,
        "devices": devices,
        "device_counts": _counts([d["status"] for d in devices]),
        "service_counts": _counts([s["status"] for d in devices for s in d["services"]]),
        "unassigned_services": [],
        "active_alerts": [
            a for a in snapshot["active_alerts"] if a["entity"].removeprefix("device ") in names
        ],
    }


async def collect_scopes(databases: Databases, run_id: int | None) -> list[Scope]:
    """The run's hosts grouped by network. A run given explicit targets covers those hosts and any host an
    agent recorded a finding for; a run given none covers every known host."""
    async with databases.app_session_factory() as session:
        run = await session.get(AiRun, run_id) if run_id is not None else None
        targets = set(run.targets) if run is not None else set()
        found = set(
            await session.scalars(select(HostFinding.ip).where(HostFinding.run_id == run_id).distinct())
        )
    snapshot = await build_snapshot(databases)
    wanted = targets | found
    devices = (
        [d for d in snapshot["devices"] if not wanted or d["ip"] in wanted]
        if targets
        else snapshot["devices"]
    )
    scopes = []
    for network in [*snapshot["networks"], {"name": UNASSIGNED, "cidr": None, "vlan_id": None}]:
        members = [d for d in devices if (d["network"] or UNASSIGNED) == network["name"]]
        if members:
            real = [network] if network["name"] != UNASSIGNED else []
            scopes.append(Scope(network["name"], _scoped(snapshot, members, real)))
    return scopes


def _demote_headings(narrative: str) -> str:
    """A model's own '# Title' would outrank the report's sections; keep its headings below them."""
    return re.sub(r"^#{1,3} ", "### ", narrative.strip(), flags=re.MULTILINE)


def _unassessed(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [d for d in devices if not d["findings"] and not d["os"]]


def _coverage(devices: list[dict[str, Any]], notes: list[str]) -> list[str]:
    missing = _unassessed(devices)
    lines = ["", "## Coverage", ""]
    lines.append(
        f"{len(devices) - len(missing)} of {len(devices)} hosts have OS, patch or other data recorded "
        "by an agent."
    )
    if missing:
        lines += ["", "Not assessed (no agent recorded anything; this is not the same as clean):", ""]
        lines += [f"- {d['name']} ({_cell(d['ip'])}), {d['status']}" for d in missing]
    lines += [f"- {note}" for note in notes]
    return lines


def _network_markdown(
    scope: Scope, run_id: int | None, delta: dict[str, Any] | None, narrative: str | None, notes: list[str]
) -> str:
    snap = scope.snapshot
    lines = [f"Run #{run_id}. Scope: {scope.name}." if run_id else f"Scope: {scope.name}."]
    if narrative:
        lines += ["", "## Analysis", "", _demote_headings(narrative)]
    lines += [
        "",
        snapshot_markdown(snap).rstrip(),
        *delta_markdown(delta),
        *_coverage(snap["devices"], notes),
    ]
    return "\n".join(lines) + "\n"


def _rollup_markdown(scopes: list[Scope], run_id: int | None, narrative: str | None, notes: list[str]) -> str:
    devices = [d for s in scopes for d in s.snapshot["devices"]]
    lines = [f"Run #{run_id}. Scope: all networks the run covered." if run_id else "Scope: all networks."]
    if narrative:
        lines += ["", "## Analysis", "", _demote_headings(narrative)]
    lines += ["", "## Networks", "", "| Network | Hosts | Up | Down | Partial | Unknown | Worst finding |"]
    lines.append("|---|---|---|---|---|---|---|")
    for scope in scopes:
        dc, hosts = scope.snapshot["device_counts"], scope.snapshot["devices"]
        worst = min(
            (SEVERITY_RANK[_worst_severity(d)] for d in hosts if _worst_severity(d) in SEVERITY_RANK),
            default=None,
        )
        assessed = any(d["findings"] for d in hosts)
        label = next(
            (n for n, r in SEVERITY_RANK.items() if r == worst),
            "no problems" if assessed else "none recorded",
        )
        lines.append(
            f"| {_cell(scope.name)} | {len(hosts)} | {dc['up']} | {dc['down']} | {dc['degraded']} | "
            f"{dc['unknown']} | {label} |"
        )
    lines += ["", "## Critical and high findings", ""]
    rows = [(f, d) for d in devices for f in d["findings"] if f["severity"] in ("critical", "high")]
    rows.sort(key=lambda r: (SEVERITY_RANK[r[0]["severity"]], r[1]["name"]))
    if rows:
        lines += ["| Severity | Host | Finding | Detail |", "|---|---|---|---|"]
        lines += [
            f"| {f['severity']} | {_cell(d['name'])} ({_cell(d['ip'])}) | {_cell(f['title'])} | "
            f"{_cell(f['detail'])} |"
            for f, d in rows
        ]
    else:
        lines.append("None recorded.")
    lines += _coverage(devices, notes)
    lines += ["", "Each network has its own report with the full host inventory, findings and changes."]
    return "\n".join(lines) + "\n"


def run_digest(scopes: list[Scope], summaries: dict[str, str]) -> str:
    """What the reporter agent is given to write its narrative from: counts, the worst findings and the
    hosts nobody assessed, per network, plus each agent's closing summary."""
    out = [
        "Run-end summary request. The run has finished and the platform is building one report per network "
        "with every host's inventory, findings and changes, so do not repeat tables or call "
        "get_status_delta. From the digest below write a short Markdown analysis: what matters most (worst "
        "findings first), what is at risk, which hosts were not assessed, and prioritised recommendations. "
        "Use only the digest; never invent findings or numbers; say plainly if nothing notable was found. "
        "Then call save_report once with a title and that Markdown, and reply with one sentence."
    ]
    for scope in scopes:
        devices = scope.snapshot["devices"]
        dc = scope.snapshot["device_counts"]
        out.append(f"\nNetwork {scope.name}: {len(devices)} hosts ({dc['up']} up, {dc['down']} down).")
        serious = sorted(
            ((f, d) for d in devices for f in d["findings"] if f["severity"] != "info"),
            key=lambda r: SEVERITY_RANK.get(r[0]["severity"], 9),
        )[:15]
        out += [
            f"- {f['severity']} on {d['name']} ({d['ip']}): {f['title']}. {f['detail']}" for f, d in serious
        ]
        missing = _unassessed(devices)
        if missing:
            out.append("- not assessed: " + ", ".join(d["name"] for d in missing[:20]))
    for agent, summary in summaries.items():
        out.append(f"\n{agent} said: {summary[:600]}")
    return "\n".join(out)


async def save_run_reports(
    databases: Databases, run_id: int, scopes: list[Scope], narrative: str | None, notes: list[str]
) -> list[int]:
    """Saves one report per network (plus the roll-up when there are several) and notifies once."""
    if not scopes:
        return []
    stamp = utcnow().strftime("%Y-%m-%d %H:%M")
    single = len(scopes) == 1
    saved: list[Report] = []
    async with databases.app_session_factory() as session:
        for scope in scopes:
            previous = await session.scalar(
                select(Report)
                .where(Report.scope == scope.name, Report.snapshot.is_not(None))
                .order_by(Report.id.desc())
                .limit(1)
            )
            delta = (
                compute_delta(previous.snapshot, scope.snapshot) if previous and previous.snapshot else None
            )
            saved.append(
                Report(
                    title=f"{scope.name} report, run #{run_id}, {stamp}",
                    source="run",
                    scope=scope.name,
                    run_id=run_id,
                    snapshot=scope.snapshot,
                    content=_network_markdown(scope, run_id, delta, narrative if single else None, notes),
                )
            )
        if not single:
            saved.append(
                Report(
                    title=f"{ALL_NETWORKS} report, run #{run_id}, {stamp}",
                    source="run",
                    scope=ALL_NETWORKS,
                    run_id=run_id,
                    content=_rollup_markdown(scopes, run_id, narrative, notes),
                )
            )
        session.add_all(saved)
        await session.commit()
        ids = [r.id for r in saved]
    notify_report_saved(databases, ids[-1])
    return ids
