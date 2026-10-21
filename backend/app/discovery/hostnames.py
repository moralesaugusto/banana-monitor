"""Where a device's host name comes from, and which source wins.

Every name carries its source. A name a human typed is never replaced; an SSH `hostname` is the host's own
word for itself; then the DNS server; then mDNS and NetBIOS answers from the device; then a name taken
from its TLS certificate. A better or equal source may replace a worse one, a worse one never replaces a
better one, so a scan cannot undo a more trustworthy name."""

import ipaddress
import re

from app.domain.models import Device

RANK = {"manual": 0, "ssh": 1, "dns": 2, "mdns": 3, "netbios": 4, "tls": 5}
_NAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]{0,251}[A-Za-z0-9])?$")
_SERIAL = re.compile(r"^[0-9A-Fa-f]{12,}$")


def clean(name: str | None) -> str | None:
    """A usable host name, or None for blanks, IP addresses, `localhost`, anything with spaces and long hex
    strings (a serial number or MAC address is an identifier, not a name)."""
    if not name:
        return None
    name = name.strip().rstrip(".")
    if not name or name.lower() == "localhost" or not _NAME.match(name) or _SERIAL.match(name):
        return None
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return name
    return None


def apply_hostname(device: Device, name: str | None, source: str | None) -> bool:
    """Sets the device's host name when `source` is at least as trustworthy as the current one. The display
    name follows only while it is still just the IP address (or the previous host name), so a name a human
    chose is left alone. Returns whether anything changed."""
    name = clean(name)
    if name is None or source not in RANK:
        return False
    if device.hostname:
        current = RANK.get(device.hostname_source or "dns", RANK["dns"])
        if RANK[source] > current:
            return False
    if device.hostname == name and device.hostname_source == source:
        return False
    previous = device.hostname
    device.hostname = name
    device.hostname_source = source
    if device.display_name in ("", device.primary_ip, previous):
        device.display_name = name
    return True
