"""Builds the Network Map graph from data the platform already holds: no
extra probing. Nodes are networks, devices, services and integrations;
edges say what contains, runs or monitors what."""

from typing import Any

from sqlalchemy import select

from app.db.session import Databases
from app.discovery.oui import get_oui_registry
from app.domain.models import Device, DeviceAddress, Integration, IntegrationTarget, Network, Service

MAX_NODES = 1500


def _fingerprint_label(service: Service) -> str | None:
    fp = service.fingerprint or {}
    product = " ".join(p for p in (fp.get("product"), fp.get("version")) if p)
    return product or fp.get("name") or fp.get("banner")


def _edge(source: str, target: str, relation: str) -> dict[str, str]:
    return {"source": source, "target": target, "relation": relation}


async def build_topology(
    databases: Databases,
    *,
    network_id: int | None = None,
    include_services: bool = True,
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []

    async with databases.app_session_factory() as session:
        networks = list((await session.execute(select(Network).order_by(Network.name))).scalars().all())
        if network_id is not None:
            networks = [n for n in networks if n.id == network_id]
        network_ids = {n.id for n in networks}

        device_query = select(Device).order_by(Device.display_name)
        if network_id is not None:
            device_query = device_query.where(Device.network_id == network_id)
        devices = list((await session.execute(device_query)).scalars().all())
        device_ids = {d.id for d in devices}

        macs: dict[int, str | None] = {}
        for address in (await session.execute(select(DeviceAddress))).scalars().all():
            if address.device_id in device_ids and (address.is_primary or address.device_id not in macs):
                macs[address.device_id] = address.mac_address

        services = list((await session.execute(select(Service).order_by(Service.name))).scalars().all())
        services = [s for s in services if s.device_id in device_ids] if network_id is not None else services
        integrations = list((await session.execute(select(Integration))).scalars().all())
        targets = list((await session.execute(select(IntegrationTarget))).scalars().all())

    truncated = False
    if len(networks) + len(devices) + len(services) > MAX_NODES:
        include_services, truncated = False, True

    oui = get_oui_registry()
    for network in networks:
        nodes.append(
            {"id": f"network:{network.id}", "kind": "network", "label": network.name,
             "subtitle": network.cidr, "status": None, "entity_id": network.id, "meta": {}}
        )
    for device in devices:
        nodes.append(
            {"id": f"device:{device.id}", "kind": "device", "label": device.display_name,
             "subtitle": device.primary_ip, "status": device.status.value, "entity_id": device.id,
             "meta": {"device_type": device.device_type.value, "managed": device.managed,
                      "vendor": oui.lookup(macs.get(device.id))}}
        )
        if device.network_id in network_ids:
            edges.append(_edge(f"network:{device.network_id}", f"device:{device.id}", "contains"))

    if include_services:
        for service in services:
            nodes.append(
                {"id": f"service:{service.id}", "kind": "service",
                 "label": f"{service.service_type.value}:{service.port}" if service.port else service.name,
                 "subtitle": _fingerprint_label(service), "status": service.status.value,
                 "entity_id": service.id, "meta": {"managed": service.managed, "source": service.source}}
            )
            if service.device_id in device_ids:
                edges.append(_edge(f"device:{service.device_id}", f"service:{service.id}", "runs"))

    node_ids = {n["id"] for n in nodes}
    monitored: set[tuple[str, str]] = set()
    for integration in integrations:
        node_id = f"integration:{integration.id}"
        linked: list[str] = []
        configured_device = integration.config.get("device_id")
        if isinstance(configured_device, int):
            linked.append(f"device:{configured_device}")
        for target in targets:
            if target.integration_id == integration.id:
                if target.device_id is not None:
                    linked.append(f"device:{target.device_id}")
                if target.service_id is not None:
                    linked.append(f"service:{target.service_id}")
        linked = [n for n in dict.fromkeys(linked) if n in node_ids]
        if network_id is not None and not linked:
            continue
        nodes.append(
            {"id": node_id, "kind": "integration", "label": integration.name,
             "subtitle": integration.integration_type,
             "status": {"ok": "up", "error": "down"}.get(integration.status.value),
             "entity_id": integration.id, "meta": {"enabled": integration.enabled}}
        )
        for target_id in linked:
            if (node_id, target_id) not in monitored:
                monitored.add((node_id, target_id))
                edges.append(_edge(node_id, target_id, "monitors"))

    return {"nodes": nodes, "edges": edges, "truncated": truncated}
