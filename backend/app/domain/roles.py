"""Human-readable device role, so a scan-discovered host isn't just "other"."""

from collections.abc import Iterable

from app.domain.enums import DeviceType

_TYPE_ROLES = {
    DeviceType.LINUX: "Linux server",
    DeviceType.WINDOWS: "Windows host",
    DeviceType.PROXMOX_NODE: "Hypervisor",
    DeviceType.PROXMOX_VM: "Virtual machine",
    DeviceType.PROXMOX_LXC: "Container",
    DeviceType.NETWORK_EQUIPMENT: "Network equipment",
    DeviceType.PLATFORM_SELF: "Monitoring platform",
}


def infer_role(device_type: DeviceType, services: Iterable[tuple[int | None, str]]) -> str:
    """`services` is (port, fingerprint text) per service; an explicit type wins over inference."""
    if device_type in _TYPE_ROLES:
        return _TYPE_ROLES[device_type]
    ports = {port for port, _ in services if port is not None}
    text = " ".join(t.lower() for _, t in services)
    if 8006 in ports or "proxmox" in text:
        return "Hypervisor"
    if 8043 in ports or 8843 in ports or "omada" in text:
        return "Network controller"
    if "adguard" in text or (53 in ports and 3000 in ports):
        return "DNS / ad-blocker"
    if 8581 in ports or 8123 in ports or "homebridge" in text or "home assistant" in text:
        return "Home automation"
    if 3389 in ports or 445 in ports:
        return "Windows / file server"
    if 22 in ports and ports & {80, 443, 8080, 8443}:
        return "Linux server"
    if 53 in ports:
        return "DNS server"
    if ports & {80, 443, 8080, 8443, 5000}:
        return "Web appliance"
    if 22 in ports:
        return "SSH host"
    return "Unclassified"
