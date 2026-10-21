"""Best-effort OS and service-version fingerprinting via the local `nmap`
binary (`nmap -O -sV`), layered on top of this app's own hand-rolled probes
(icmp/tcp_ports/http_probe/tls_probe) rather than replacing them - nmap is
one more opinion, used when it's available and permitted, never required.

`-O` (TCP/IP OS fingerprinting) needs raw-socket access, which means root or
`CAP_NET_RAW`/`CAP_NET_ADMIN` - the systemd unit runs as an unprivileged
`banana` user by default (see deploy/banana.service), so on a stock install
this will fail with nmap's own "requires root privileges" message every
time. That failure is expected and handled: a single warning is logged the
first time it happens per process (not once per host, which would spam the
log every scan cycle), and scanning proceeds exactly as it did before this
module existed. Grant the unit `AmbientCapabilities=CAP_NET_RAW` (see
docs/deployment.md) to actually get OS results.
"""

import asyncio
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from app.discovery.techniques.subprocess_runner import SubprocessRunner, default_subprocess_runner
from app.logging_setup import get_logger

logger = get_logger(__name__)

NMAP_TIMEOUT_SECONDS = 20.0
_warned_unavailable = False


@dataclass
class NmapResult:
    os_name: str | None
    os_accuracy: int | None
    services: dict[int, dict[str, str]] = field(default_factory=dict)


def _parse_nmap_xml(xml_text: str) -> NmapResult:
    root = ET.fromstring(xml_text)
    host = root.find("host")
    if host is None:
        return NmapResult(os_name=None, os_accuracy=None)

    os_name: str | None = None
    os_accuracy: int | None = None
    osmatch = host.find("./os/osmatch")
    if osmatch is not None:
        os_name = osmatch.get("name")
        accuracy = osmatch.get("accuracy")
        os_accuracy = int(accuracy) if accuracy is not None else None

    services: dict[int, dict[str, str]] = {}
    for port_el in host.findall("./ports/port"):
        portid = port_el.get("portid")
        if portid is None:
            continue
        service_el = port_el.find("service")
        if service_el is None:
            continue
        info = {
            key: value
            for key, value in (
                ("product", service_el.get("product")),
                ("version", service_el.get("version")),
                ("extrainfo", service_el.get("extrainfo")),
            )
            if value
        }
        if info:
            services[int(portid)] = info

    return NmapResult(os_name=os_name, os_accuracy=os_accuracy, services=services)


async def scan_host(
    ip: str,
    timeout: float = NMAP_TIMEOUT_SECONDS,
    runner: SubprocessRunner = default_subprocess_runner,
) -> NmapResult | None:
    """Returns best-effort OS/service info for `ip`, or None if nmap isn't
    installed, isn't permitted to do OS fingerprinting, or times out - any of
    which just means "no extra info this cycle", never a scan failure."""
    global _warned_unavailable
    try:
        returncode, stdout, stderr = await asyncio.wait_for(
            runner(["nmap", "-O", "--osscan-guess", "-sV", "-oX", "-", ip]), timeout
        )
    except FileNotFoundError:
        if not _warned_unavailable:
            logger.warning("nmap_not_installed", detail="OS/service fingerprinting disabled")
            _warned_unavailable = True
        return None
    except TimeoutError:
        logger.debug("nmap_scan_timed_out", ip=ip)
        return None

    if returncode != 0:
        if "requires root privileges" in stderr and not _warned_unavailable:
            logger.warning(
                "nmap_os_detection_unprivileged",
                detail="nmap -O needs CAP_NET_RAW/root - see docs/deployment.md",
            )
            _warned_unavailable = True
        else:
            logger.debug("nmap_scan_failed", ip=ip, returncode=returncode, stderr=stderr[:200])
        return None

    try:
        return _parse_nmap_xml(stdout)
    except ET.ParseError:
        logger.debug("nmap_output_unparseable", ip=ip)
        return None


@dataclass
class NmapTuning:
    """Aggressive-by-default timing for service identification. Every knob
    maps to one nmap flag; values come from the persisted DiscoverySettings."""

    timing_template: int = 4
    host_timeout_seconds: int = 30
    max_retries: int = 1
    version_intensity: int = 2


def build_service_scan_args(ip: str, ports: list[int], tuning: NmapTuning) -> list[str]:
    """-Pn: the host is already known to have these ports open, so skip host
    discovery. No -O, so this needs no raw-socket privileges (connect scan)."""
    return [
        "nmap",
        "-Pn",
        "-sT",
        "-sV",
        f"-T{tuning.timing_template}",
        f"--version-intensity={tuning.version_intensity}",
        f"--host-timeout={tuning.host_timeout_seconds}s",
        f"--max-retries={tuning.max_retries}",
        "-p",
        ",".join(str(p) for p in sorted(ports)),
        "-oX",
        "-",
        ip,
    ]


def parse_service_scan_xml(xml_text: str) -> dict[int, dict[str, str]]:
    """port -> {name, product, version, extrainfo, tunnel} for open ports only."""
    host = ET.fromstring(xml_text).find("host")
    if host is None:
        return {}
    result: dict[int, dict[str, str]] = {}
    for port_el in host.findall("./ports/port"):
        state = port_el.find("state")
        service_el = port_el.find("service")
        portid = port_el.get("portid")
        if portid is None or state is None or state.get("state") != "open" or service_el is None:
            continue
        info = {
            key: value
            for key in ("name", "product", "version", "extrainfo", "tunnel")
            if (value := service_el.get(key))
        }
        if info:
            result[int(portid)] = info
    return result


async def fingerprint_services(
    ip: str,
    ports: list[int],
    tuning: NmapTuning,
    runner: SubprocessRunner = default_subprocess_runner,
) -> dict[int, dict[str, str]]:
    """Runs one `nmap -sV` over the given open ports. Returns {} when nmap is
    missing, fails or times out - fingerprinting is additive, never required."""
    if not ports:
        return {}
    # Hard cap just above nmap's own --host-timeout so a wedged process can't linger.
    hard_timeout = tuning.host_timeout_seconds + 10.0
    try:
        returncode, stdout, stderr = await asyncio.wait_for(
            runner(build_service_scan_args(ip, ports, tuning)), hard_timeout
        )
    except FileNotFoundError:
        logger.warning("nmap_not_installed", detail="service fingerprinting disabled")
        return {}
    except TimeoutError:
        logger.debug("nmap_service_scan_timed_out", ip=ip)
        return {}
    if returncode != 0:
        logger.debug("nmap_service_scan_failed", ip=ip, returncode=returncode, stderr=stderr[:200])
        return {}
    try:
        return parse_service_scan_xml(stdout)
    except ET.ParseError:
        logger.debug("nmap_service_output_unparseable", ip=ip)
        return {}


def service_type_for(info: dict[str, str], port: int) -> str:
    """Maps nmap's service name onto this app's ServiceType values."""
    name = info.get("name", "")
    if name.startswith("http"):
        return "https" if info.get("tunnel") == "ssl" or name == "https" else "http"
    if name == "domain":
        return "dns"
    return "tcp"
