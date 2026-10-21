"""Builds the network and services report from the database. The snapshot is plain data; the Markdown
renderer turns it into a report without any model, so a report is always available even when the
Ollama host is down. The reporter agent reads the same snapshot and writes a narrative version."""

import datetime
from typing import Any

from sqlalchemy import select

from app.db.session import Databases
from app.domain.enums import AlertState, HealthStatus
from app.domain.models import AlertStateRow, Device, Network, Service, utcnow


def _fingerprint_text(fp: dict[str, Any] | None) -> str:
    if not fp:
        return ""
    product = " ".join(str(v) for v in (fp.get("product"), fp.get("version")) if v)
    return product or str(fp.get("name") or fp.get("banner") or "")


async def build_snapshot(databases: Databases) -> dict[str, Any]:
    async with databases.app_session_factory() as session:
        networks = list((await session.execute(select(Network).order_by(Network.name))).scalars())
        devices = list((await session.execute(select(Device).order_by(Device.display_name))).scalars())
        services = list(
            (await session.execute(select(Service).order_by(Service.port, Service.name))).scalars()
        )
        firing = list(
            (
                await session.execute(
                    select(AlertStateRow).where(AlertStateRow.state != AlertState.OK)
                )
            ).scalars()
        )

        by_device: dict[int | None, list[Service]] = {}
        for service in services:
            by_device.setdefault(service.device_id, []).append(service)

        network_names: dict[int | None, str] = {n.id: n.name for n in networks}
        device_rows = [
            {
                "name": d.display_name,
                "ip": d.primary_ip,
                "type": d.device_type.value,
                "status": d.status.value,
                "network": network_names.get(d.network_id),
                "managed": d.managed,
                "last_seen": d.last_seen_at.isoformat() if d.last_seen_at else None,
                "services": [
                    {
                        "name": s.name,
                        "type": s.service_type.value,
                        "port": s.port,
                        "status": s.status.value,
                        "managed": s.managed,
                        "fingerprint": _fingerprint_text(s.fingerprint),
                        "latency_ms": None,
                    }
                    for s in by_device.get(d.id, [])
                ],
            }
            for d in devices
        ]

        def counts(statuses: list[HealthStatus]) -> dict[str, int]:
            result = {s.value: 0 for s in HealthStatus}
            for status in statuses:
                result[status.value] += 1
            return result

        device_names = {d.id: d.display_name for d in devices}
        return {
            "generated_at": utcnow().isoformat(timespec="seconds"),
            "networks": [{"name": n.name, "cidr": n.cidr, "vlan_id": n.vlan_id} for n in networks],
            "device_counts": counts([d.status for d in devices]),
            "service_counts": counts([s.status for s in services]),
            "devices": device_rows,
            "unassigned_services": [
                {"name": s.name, "type": s.service_type.value, "port": s.port, "status": s.status.value}
                for s in by_device.get(None, [])
            ],
            "active_alerts": [
                {
                    "rule": a.rule.name,
                    "entity": f"{a.entity_type.value} {device_names.get(a.entity_id, a.entity_id)}"
                    if a.entity_type.value == "device"
                    else f"{a.entity_type.value} {a.entity_id}",
                    "state": a.state.value,
                    "since": a.state_changed_at.isoformat(timespec="seconds"),
                }
                for a in firing
            ],
        }


def _device_key(device: dict[str, Any]) -> str:
    return str(device.get("ip") or device["name"])


def _service_key(device_key: str, service: dict[str, Any]) -> str:
    return f"{device_key}:{service['name']}:{service['port']}"


def _alert_key(alert: dict[str, Any]) -> str:
    return f"{alert['rule']}|{alert['entity']}"


def compute_delta(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """What changed between two build_snapshot() results: devices/services that appeared or
    disappeared, status changes for ones present in both, and alerts that newly fired or resolved.
    Computed here, in code, rather than left for a model to eyeball two raw snapshots - the same
    reasoning as every other structured tool result in this codebase."""
    prev_devices = {_device_key(d): d for d in previous.get("devices", [])}
    curr_devices = {_device_key(d): d for d in current.get("devices", [])}

    devices_added = [curr_devices[k]["name"] for k in curr_devices if k not in prev_devices]
    devices_removed = [prev_devices[k]["name"] for k in prev_devices if k not in curr_devices]

    device_status_changes = []
    service_status_changes = []
    for key, curr in curr_devices.items():
        prev = prev_devices.get(key)
        if prev is None:
            continue
        if prev["status"] != curr["status"]:
            device_status_changes.append(
                {"name": curr["name"], "ip": curr.get("ip"), "from": prev["status"], "to": curr["status"]}
            )
        prev_services = {_service_key(key, s): s for s in prev.get("services", [])}
        curr_services = {_service_key(key, s): s for s in curr.get("services", [])}
        for skey, cs in curr_services.items():
            ps = prev_services.get(skey)
            if ps is not None and ps["status"] != cs["status"]:
                service_status_changes.append(
                    {
                        "device": curr["name"],
                        "service": cs["name"],
                        "port": cs["port"],
                        "from": ps["status"],
                        "to": cs["status"],
                    }
                )

    prev_alerts = {_alert_key(a): a for a in previous.get("active_alerts", [])}
    curr_alerts = {_alert_key(a): a for a in current.get("active_alerts", [])}
    new_alerts = [curr_alerts[k] for k in curr_alerts if k not in prev_alerts]
    resolved_alerts = [prev_alerts[k] for k in prev_alerts if k not in curr_alerts]

    return {
        "since": previous.get("generated_at"),
        "devices_added": devices_added,
        "devices_removed": devices_removed,
        "device_status_changes": device_status_changes,
        "service_status_changes": service_status_changes,
        "new_alerts": new_alerts,
        "resolved_alerts": resolved_alerts,
    }


def _cell(value: object) -> str:
    return str(value if value not in (None, "") else "-").replace("|", "/")


def snapshot_markdown(snapshot: dict[str, Any]) -> str:
    dc, sc = snapshot["device_counts"], snapshot["service_counts"]
    lines = [
        f"Generated {snapshot['generated_at']} UTC.",
        "",
        "## Summary",
        "",
        f"- Devices: {sum(dc.values())} ({dc['up']} up, {dc['degraded']} partial, {dc['down']} down, "
        f"{dc['unknown']} unknown)",
        f"- Services: {sum(sc.values())} ({sc['up']} up, {sc['degraded']} degraded, {sc['down']} down, "
        f"{sc['unknown']} unknown)",
        f"- Active alerts: {len(snapshot['active_alerts'])}",
        "",
        "## Networks",
        "",
    ]
    if snapshot["networks"]:
        lines += ["| Name | CIDR | VLAN |", "|---|---|---|"]
        lines += [
            f"| {_cell(n['name'])} | {_cell(n['cidr'])} | {_cell(n['vlan_id'])} |"
            for n in snapshot["networks"]
        ]
    else:
        lines.append("No networks configured.")

    lines += ["", "## Devices", ""]
    if snapshot["devices"]:
        lines += ["| Name | IP | Type | Network | Status | Services |", "|---|---|---|---|---|---|"]
        lines += [
            f"| {_cell(d['name'])} | {_cell(d['ip'])} | {_cell(d['type'])} | {_cell(d['network'])} | "
            f"{d['status']} | {len(d['services'])} |"
            for d in snapshot["devices"]
        ]
    else:
        lines.append("No devices yet.")

    lines += ["", "## Services by host", ""]
    shown = False
    for d in snapshot["devices"]:
        if not d["services"]:
            continue
        shown = True
        lines += [
            f"### {d['name']} ({d['ip'] or 'no IP'})",
            "",
            "| Service | Type | Port | Fingerprint | Status |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {_cell(s['name'])}{'' if s['managed'] else ' (discovered)'} | {s['type']} | "
            f"{_cell(s['port'])} | "
            f"{_cell(s['fingerprint'])} | {s['status']} |"
            for s in d["services"]
        ]
        lines.append("")
    if snapshot["unassigned_services"]:
        shown = True
        lines += [
            "### Not assigned to a device",
            "",
            "| Service | Type | Port | Status |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {_cell(s['name'])} | {s['type']} | {_cell(s['port'])} | {s['status']} |"
            for s in snapshot["unassigned_services"]
        ]
        lines.append("")
    if not shown:
        lines.append("No services recorded.")

    lines += ["", "## Active alerts", ""]
    if snapshot["active_alerts"]:
        lines += ["| Rule | Entity | State | Since |", "|---|---|---|---|"]
        lines += [
            f"| {_cell(a['rule'])} | {_cell(a['entity'])} | {a['state']} | {a['since']} |"
            for a in snapshot["active_alerts"]
        ]
    else:
        lines.append("None.")

    attention = [
        f"- {d['name']} is {d['status']}" for d in snapshot["devices"] if d["status"] in ("down", "degraded")
    ] + [
        f"- {d['name']}: {s['name']} on port {s['port']} is {s['status']}"
        for d in snapshot["devices"]
        for s in d["services"]
        if s["status"] == "down"
    ]
    lines += ["", "## Needs attention", ""]
    lines += attention or ["Nothing is down or degraded."]
    return "\n".join(lines) + "\n"


def default_title(now: datetime.datetime | None = None) -> str:
    return f"Network report {(now or utcnow()).strftime('%Y-%m-%d %H:%M')}"
