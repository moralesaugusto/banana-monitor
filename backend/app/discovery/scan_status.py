"""In-memory per-network scan progress, for the Networks page's live
"Scanning... N/M hosts" indicator (`GET /api/networks/{id}/scan-status`).

Deliberately in-process, not persisted to app.db: a scan in progress when the
process restarts is simply abandoned (`trigger_scan` fires it through
`app.background.spawn`), so
there is nothing meaningful to recover across a restart - the same reasoning
`PollingSupervisor` already applies to its own task bookkeeping.
"""

import datetime
from dataclasses import dataclass
from functools import lru_cache

from app.domain.models import utcnow


@dataclass
class ScanStatus:
    network_id: int
    status: str = "idle"  # "idle" | "scanning"
    total_hosts: int = 0
    scanned_hosts: int = 0
    started_at: datetime.datetime | None = None
    finished_at: datetime.datetime | None = None
    failed_hosts: int = 0
    """Hosts whose scan raised; the scan carries on without them."""
    error: str | None = None
    """Set when the whole scan failed (not just one host)."""


class ScanStatusRegistry:
    def __init__(self) -> None:
        self._statuses: dict[int, ScanStatus] = {}

    def get(self, network_id: int) -> ScanStatus:
        return self._statuses.get(network_id) or ScanStatus(network_id=network_id)

    def all(self) -> list[ScanStatus]:
        return list(self._statuses.values())

    def start(self, network_id: int, total_hosts: int) -> None:
        self._statuses[network_id] = ScanStatus(
            network_id=network_id, status="scanning", total_hosts=total_hosts, started_at=utcnow()
        )

    def advance(self, network_id: int) -> None:
        status = self._statuses.get(network_id)
        if status is not None:
            status.scanned_hosts += 1

    def host_failed(self, network_id: int) -> None:
        status = self._statuses.get(network_id)
        if status is not None:
            status.failed_hosts += 1

    def fail(self, network_id: int, error: str) -> None:
        status = self._statuses.setdefault(network_id, ScanStatus(network_id=network_id))
        status.error = error

    def finish(self, network_id: int) -> None:
        status = self._statuses.get(network_id)
        if status is not None:
            status.status = "idle"
            status.finished_at = utcnow()


@lru_cache
def get_scan_status_registry() -> ScanStatusRegistry:
    return ScanStatusRegistry()
