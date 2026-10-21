"""The chat assistant's tool surface: read access across the platform plus a
curated safe-write set. Deliberately excludes deletes and any
credential/integration mutation - those tools simply do not exist here, so
the model cannot attempt them regardless of what it's asked. Each handler
opens its own session(s) and does the same direct-SQLAlchemy work as the
corresponding route, rather than calling route functions (which are wired to
FastAPI's request-scoped dependency injection).
"""

from typing import Any

from sqlalchemy import func, select

from app.background import spawn
from app.db.session import Databases
from app.discovery.network_scanner import scan_network
from app.discovery.oui import get_oui_registry
from app.discovery.service import DiscoveryService
from app.domain.enums import (
    AlertState,
    CandidateStatus,
    DeviceType,
    EntityType,
    HealthStatus,
    IntegrationStatus,
    ServiceType,
)
from app.domain.models import (
    AlertRule,
    AlertStateRow,
    Device,
    DeviceAddress,
    Event,
    Integration,
    Network,
    Service,
)
from app.integrations import registry as plugin_registry
from app.metrics.queries import get_latest_metric_values
from app.scheduler.supervisor import SERVICE_TYPE_TO_PLUGIN, get_supervisor


class ToolExecutionError(RuntimeError):
    pass


def _device_summary(device: Device) -> dict[str, Any]:
    return {
        "id": device.id,
        "display_name": device.display_name,
        "hostname": device.hostname,
        "primary_ip": device.primary_ip,
        "device_type": device.device_type.value,
        "status": device.status.value,
        "managed": device.managed,
        "tags": device.tags,
    }


def _service_summary(service: Service, latency_ms: float | None) -> dict[str, Any]:
    return {
        "id": service.id,
        "name": service.name,
        "service_type": service.service_type.value,
        "device_id": service.device_id,
        "status": service.status.value,
        "managed": service.managed,
        "last_latency_ms": latency_ms,
    }


async def _get_overview(databases: Databases, arguments: dict[str, Any]) -> Any:
    async with databases.app_session_factory() as session:
        device_counts = {s.value: 0 for s in HealthStatus}
        result = await session.execute(select(Device.status, func.count()).group_by(Device.status))
        for status, count in result.all():
            device_counts[status.value] = count

        service_counts = {s.value: 0 for s in HealthStatus}
        result = await session.execute(select(Service.status, func.count()).group_by(Service.status))
        for status, count in result.all():
            service_counts[status.value] = count

        integration_result = await session.execute(
            select(Integration.status, func.count()).group_by(Integration.status)
        )
        integration_counts = {status: count for status, count in integration_result.all()}

        firing_result = await session.execute(
            select(AlertStateRow)
            .where(AlertStateRow.state.in_([AlertState.FIRING, AlertState.FLAPPING]))
            .order_by(AlertStateRow.state_changed_at.desc())
            .limit(20)
        )
        firing = [
            {
                "id": a.id,
                "alert_rule_id": a.alert_rule_id,
                "entity_type": a.entity_type.value,
                "entity_id": a.entity_id,
                "state": a.state.value,
                "state_changed_at": a.state_changed_at.isoformat(),
            }
            for a in firing_result.scalars().all()
        ]

        return {
            "devices": device_counts,
            "services": service_counts,
            "integrations_ok": integration_counts.get(IntegrationStatus.OK, 0),
            "integrations_error": integration_counts.get(IntegrationStatus.ERROR, 0),
            "firing_alerts": firing,
        }


async def _list_devices(databases: Databases, arguments: dict[str, Any]) -> Any:
    status = arguments.get("status")
    async with databases.app_session_factory() as session:
        stmt = select(Device).order_by(Device.display_name)
        if status:
            try:
                stmt = stmt.where(Device.status == HealthStatus(status))
            except ValueError as exc:
                raise ToolExecutionError(f"Invalid status {status!r}") from exc
        result = await session.execute(stmt)
        return [_device_summary(d) for d in result.scalars().all()]


async def _get_device(databases: Databases, arguments: dict[str, Any]) -> Any:
    device_id = _require_int(arguments, "device_id")
    async with databases.app_session_factory() as session:
        device = await session.get(Device, device_id)
        if device is None:
            raise ToolExecutionError(f"Device {device_id} not found")
        addr_result = await session.execute(
            select(DeviceAddress).where(DeviceAddress.device_id == device_id)
        )
        registry = get_oui_registry()
        addresses = [
            {
                "ip_address": a.ip_address,
                "mac_address": a.mac_address,
                "is_primary": a.is_primary,
                "vendor": registry.lookup(a.mac_address),
            }
            for a in addr_result.scalars().all()
        ]
        svc_result = await session.execute(select(Service).where(Service.device_id == device_id))
        services = [
            {"id": s.id, "name": s.name, "status": s.status.value} for s in svc_result.scalars().all()
        ]
        return {**_device_summary(device), "addresses": addresses, "services": services}


async def _list_services(databases: Databases, arguments: dict[str, Any]) -> Any:
    status = arguments.get("status")
    device_id = arguments.get("device_id")
    async with databases.app_session_factory() as session:
        stmt = select(Service).order_by(Service.name)
        if status:
            try:
                stmt = stmt.where(Service.status == HealthStatus(status))
            except ValueError as exc:
                raise ToolExecutionError(f"Invalid status {status!r}") from exc
        if device_id is not None:
            stmt = stmt.where(Service.device_id == int(device_id))
        result = await session.execute(stmt)
        services = list(result.scalars().all())

    async with databases.metrics_session_factory() as metrics_session:
        latencies = await get_latest_metric_values(
            metrics_session, EntityType.SERVICE, "latency_ms", [s.id for s in services]
        )
    return [_service_summary(s, latencies.get(s.id)) for s in services]


async def _list_alerts(databases: Databases, arguments: dict[str, Any]) -> Any:
    active_only = arguments.get("active_only", True)
    async with databases.app_session_factory() as session:
        stmt = select(AlertStateRow).order_by(AlertStateRow.state_changed_at.desc())
        if active_only:
            stmt = stmt.where(AlertStateRow.state != AlertState.OK)
        result = await session.execute(stmt)
        return [
            {
                "id": a.id,
                "alert_rule_id": a.alert_rule_id,
                "entity_type": a.entity_type.value,
                "entity_id": a.entity_id,
                "state": a.state.value,
                "state_changed_at": a.state_changed_at.isoformat(),
            }
            for a in result.scalars().all()
        ]


async def _list_events(databases: Databases, arguments: dict[str, Any]) -> Any:
    limit = int(arguments.get("limit", 50))
    async with databases.app_session_factory() as session:
        result = await session.execute(select(Event).order_by(Event.ts.desc()).limit(limit))
        return [
            {
                "id": e.id,
                "ts": e.ts.isoformat(),
                "source": e.source,
                "severity": e.severity.value,
                "category": e.category,
                "message": e.message,
            }
            for e in result.scalars().all()
        ]


async def _list_discovery_candidates(databases: Databases, arguments: dict[str, Any]) -> Any:
    status_str = arguments.get("status", "pending")
    try:
        status = CandidateStatus(status_str)
    except ValueError as exc:
        raise ToolExecutionError(f"Invalid status {status_str!r}") from exc
    candidates = await DiscoveryService(databases).list_candidates(status)
    return [
        {
            "id": c.id,
            "candidate_type": c.candidate_type.value,
            "raw_attributes": c.raw_attributes,
            "times_seen": c.times_seen,
            "last_seen_at": c.last_seen_at.isoformat(),
        }
        for c in candidates
    ]


async def _list_networks(databases: Databases, arguments: dict[str, Any]) -> Any:
    async with databases.app_session_factory() as session:
        result = await session.execute(select(Network).order_by(Network.name))
        return [
            {"id": n.id, "name": n.name, "cidr": n.cidr, "vlan_id": n.vlan_id}
            for n in result.scalars().all()
        ]


async def _accept_discovery_candidate_as_service(databases: Databases, arguments: dict[str, Any]) -> Any:
    candidate_id = _require_int(arguments, "candidate_id")
    service_type_str = _require_str(arguments, "service_type")
    try:
        service_type = ServiceType(service_type_str)
    except ValueError as exc:
        raise ToolExecutionError(f"Invalid service_type {service_type_str!r}") from exc
    name = arguments.get("name")
    device_id = arguments.get("device_id")
    config = arguments.get("config") or {}
    try:
        service = await DiscoveryService(databases).accept_service(
            candidate_id, service_type, name, device_id, config
        )
    except Exception as exc:  # noqa: BLE001
        raise ToolExecutionError(str(exc)) from exc
    get_supervisor().add_target(service)
    return _service_summary(service, None)


async def _ignore_discovery_candidate(databases: Databases, arguments: dict[str, Any]) -> Any:
    candidate_id = _require_int(arguments, "candidate_id")
    try:
        await DiscoveryService(databases).ignore(candidate_id)
    except Exception as exc:  # noqa: BLE001
        raise ToolExecutionError(str(exc)) from exc
    return {"ok": True}


_UPDATE_DEVICE_FIELDS = {"display_name", "notes", "tags", "device_type"}


async def _update_device(databases: Databases, arguments: dict[str, Any]) -> Any:
    device_id = _require_int(arguments, "device_id")
    updates = {k: v for k, v in arguments.items() if k in _UPDATE_DEVICE_FIELDS and v is not None}
    if "device_type" in updates:
        try:
            updates["device_type"] = DeviceType(updates["device_type"])
        except ValueError as exc:
            raise ToolExecutionError(f"Invalid device_type {updates['device_type']!r}") from exc

    async with databases.app_session_factory() as session:
        device = await session.get(Device, device_id)
        if device is None:
            raise ToolExecutionError(f"Device {device_id} not found")
        for field, value in updates.items():
            setattr(device, field, value)
        await session.commit()
        await session.refresh(device)
        return _device_summary(device)


async def _validate_service_config(service_type: ServiceType, config: dict[str, Any]) -> None:
    plugin_key = SERVICE_TYPE_TO_PLUGIN.get(service_type)
    if plugin_key is None:
        return
    plugin = plugin_registry.get_plugin(plugin_key)
    if plugin is None:
        return
    result = await plugin.validate_config(config, None)
    if not result.ok:
        raise ToolExecutionError(result.message or "Invalid service config")


async def _create_service(databases: Databases, arguments: dict[str, Any]) -> Any:
    name = _require_str(arguments, "name")
    service_type_str = _require_str(arguments, "service_type")
    try:
        service_type = ServiceType(service_type_str)
    except ValueError as exc:
        raise ToolExecutionError(f"Invalid service_type {service_type_str!r}") from exc
    device_id = arguments.get("device_id")
    config = arguments.get("config") or {}
    await _validate_service_config(service_type, config)

    async with databases.app_session_factory() as session:
        service = Service(device_id=device_id, name=name, service_type=service_type, config=config)
        session.add(service)
        await session.commit()
        await session.refresh(service)
    get_supervisor().add_target(service)
    return _service_summary(service, None)


async def _update_service(databases: Databases, arguments: dict[str, Any]) -> Any:
    service_id = _require_int(arguments, "service_id")
    async with databases.app_session_factory() as session:
        service = await session.get(Service, service_id)
        if service is None:
            raise ToolExecutionError(f"Service {service_id} not found")
        if arguments.get("name") is not None:
            service.name = arguments["name"]
        if arguments.get("config") is not None:
            await _validate_service_config(service.service_type, arguments["config"])
            service.config = arguments["config"]
        await session.commit()
        await session.refresh(service)
    get_supervisor().reload_target(service)
    return _service_summary(service, None)


async def _trigger_network_scan(databases: Databases, arguments: dict[str, Any]) -> Any:
    network_id = _require_int(arguments, "network_id")
    async with databases.app_session_factory() as session:
        network = await session.get(Network, network_id)
        if network is None:
            raise ToolExecutionError(f"Network {network_id} not found")
    spawn(scan_network(databases, network_id), f"scan-network-{network_id}")
    return {"status": "scan started", "network_id": network_id}


async def _set_alert_rule_enabled(databases: Databases, arguments: dict[str, Any]) -> Any:
    rule_id = _require_int(arguments, "rule_id")
    enabled = bool(arguments.get("enabled", True))
    async with databases.app_session_factory() as session:
        rule = await session.get(AlertRule, rule_id)
        if rule is None:
            raise ToolExecutionError(f"Alert rule {rule_id} not found")
        rule.enabled = enabled
        await session.commit()
        return {"id": rule.id, "name": rule.name, "enabled": rule.enabled}


def _require_int(arguments: dict[str, Any], key: str) -> int:
    if key not in arguments or arguments[key] is None:
        raise ToolExecutionError(f"Missing required argument {key!r}")
    try:
        return int(arguments[key])
    except (TypeError, ValueError) as exc:
        raise ToolExecutionError(f"Argument {key!r} must be an integer") from exc


def _require_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not value:
        raise ToolExecutionError(f"Missing required argument {key!r}")
    return str(value)


_HANDLERS = {
    "get_overview": _get_overview,
    "list_devices": _list_devices,
    "get_device": _get_device,
    "list_services": _list_services,
    "list_alerts": _list_alerts,
    "list_events": _list_events,
    "list_discovery_candidates": _list_discovery_candidates,
    "list_networks": _list_networks,
    "accept_discovery_candidate_as_service": _accept_discovery_candidate_as_service,
    "ignore_discovery_candidate": _ignore_discovery_candidate,
    "update_device": _update_device,
    "create_service": _create_service,
    "update_service": _update_service,
    "trigger_network_scan": _trigger_network_scan,
    "set_alert_rule_enabled": _set_alert_rule_enabled,
}

WRITE_TOOL_NAMES = frozenset(
    {
        "accept_discovery_candidate_as_service",
        "ignore_discovery_candidate",
        "update_device",
        "create_service",
        "update_service",
        "trigger_network_scan",
        "set_alert_rule_enabled",
    }
)
"""The chat assistant's safe-write tools, gated by AssistantConfig.full_access. Every other tool in
_HANDLERS is read-only and always allowed. This is the single source of truth dispatch_tool_call
enforces against and READ_ONLY_TOOL_SCHEMAS below is filtered from - keep it in sync with _HANDLERS."""


async def dispatch_tool_call(
    databases: Databases, name: str, arguments: dict[str, Any], *, full_access: bool = True
) -> Any:
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ToolExecutionError(f"Unknown tool {name!r}")
    if name in WRITE_TOOL_NAMES and not full_access:
        raise ToolExecutionError(
            f"{name!r} is a write action and the assistant is in read-only mode. Turn on full access "
            "(AI Mode > Settings > Chat assistant) to allow it."
        )
    return await handler(databases, arguments)


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_overview",
            "description": (
                "Get platform-wide status counts: devices/services by health status, "
                "integration ok/error counts, and currently firing/flapping alerts."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_devices",
            "description": "List monitored devices, optionally filtered by status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": [s.value for s in HealthStatus]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_device",
            "description": (
                "Get full detail for one device: addresses (with IEEE OUI vendor guess), attached services."
            ),
            "parameters": {
                "type": "object",
                "properties": {"device_id": {"type": "integer"}},
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_services",
            "description": "List monitored services, optionally filtered by status and/or parent device.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": [s.value for s in HealthStatus]},
                    "device_id": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_alerts",
            "description": (
                "List alert rule states. By default only non-ok (pending/firing/resolved/flapping) states."
            ),
            "parameters": {
                "type": "object",
                "properties": {"active_only": {"type": "boolean", "default": True}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_events",
            "description": "List the most recent platform events (discovery, alerts, etc).",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 50}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_discovery_candidates",
            "description": "List discovered devices/services awaiting review (default status=pending).",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": [s.value for s in CandidateStatus]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_networks",
            "description": "List configured networks (site CIDRs scoped for discovery scanning).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "accept_discovery_candidate_as_service",
            "description": (
                "Accept a pending SERVICE discovery candidate, creating a real monitored Service "
                "and starting it polling immediately."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "integer"},
                    "service_type": {"type": "string", "enum": [t.value for t in ServiceType]},
                    "name": {"type": "string"},
                    "device_id": {"type": "integer"},
                    "config": {"type": "object"},
                },
                "required": ["candidate_id", "service_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ignore_discovery_candidate",
            "description": "Mark a discovery candidate as ignored so it stops appearing in the review queue.",
            "parameters": {
                "type": "object",
                "properties": {"candidate_id": {"type": "integer"}},
                "required": ["candidate_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_device",
            "description": (
                "Update a device's display name, notes, tags, or device type. "
                "Cannot change its IP/network or managed flag."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer"},
                    "display_name": {"type": "string"},
                    "notes": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "device_type": {"type": "string", "enum": [t.value for t in DeviceType]},
                },
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_service",
            "description": (
                "Create a new monitored service (http/https/tcp/dns/dhcp) and start polling it immediately."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "service_type": {"type": "string", "enum": [t.value for t in ServiceType]},
                    "device_id": {"type": "integer"},
                    "config": {
                        "type": "object",
                        "description": 'e.g. {"url": "https://host"} or {"host": "...", "port": 22}',
                    },
                },
                "required": ["name", "service_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_service",
            "description": (
                "Update a service's name and/or check config. "
                "Cannot change its type, device, or managed flag."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {"type": "integer"},
                    "name": {"type": "string"},
                    "config": {"type": "object"},
                },
                "required": ["service_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_network_scan",
            "description": "Start a discovery scan of one configured network in the background.",
            "parameters": {
                "type": "object",
                "properties": {"network_id": {"type": "integer"}},
                "required": ["network_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_alert_rule_enabled",
            "description": "Enable or disable an existing alert rule. Cannot edit its condition/threshold.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rule_id": {"type": "integer"},
                    "enabled": {"type": "boolean"},
                },
                "required": ["rule_id", "enabled"],
            },
        },
    },
]

READ_ONLY_TOOL_SCHEMAS: list[dict[str, Any]] = [
    schema for schema in TOOL_SCHEMAS if schema["function"]["name"] not in WRITE_TOOL_NAMES
]
"""What the model is offered when AssistantConfig.full_access is off - the write tools are not just
refused on use, they are never even named to the model."""
