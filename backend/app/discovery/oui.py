"""IEEE OUI (Organizationally Unique Identifier) registry.

Maps a MAC address's first 3 octets to the vendor that IEEE assigned that
block to, for best-effort device identification during discovery (a MAC's
vendor is often a strong hint for what a device is - "Ubiquiti Networks",
"Raspberry Pi Foundation", "Apple, Inc.", etc).

Cached locally as a flat file under `Settings.data_dir` and loaded from
there on first use - never downloaded automatically at startup, so a LAN
with no internet reachability still starts and scans normally, just
without vendor hints, consistent with this app's graceful-degradation
requirements (see AGENTS.md). Refreshed only when `OuiRegistry.update()`
is called, i.e. the Discovery page's "Update vendor database" button /
`POST /api/discovery/oui/update`.

Only the standard 24-bit MA-L registry (`oui.csv`) is used. IEEE's smaller
MA-M/MA-S blocks exist for organizations that need fewer addresses than a
full /24 worth of MACs, but supporting them would mean matching variable-
length prefixes for a marginal home-lab benefit - not implemented here.
"""

import csv
import datetime
import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx

from app.config import Settings, get_settings
from app.logging_setup import get_logger

logger = get_logger(__name__)

IEEE_OUI_CSV_URL = "https://standards-oui.ieee.org/oui/oui.csv"
DOWNLOAD_TIMEOUT_SECONDS = 30.0
CACHE_FILENAME = "oui_cache.csv"
# IEEE's edge/WAF returns 418 for httpx's default "python-httpx/x.y" User-Agent
# (a plain `curl` with no UA override, or any browser-like one, passes) - send
# an ordinary browser UA purely to get past that bot-sniffing, not to spoof
# identity against any access control (this endpoint serves a public CSV with
# no auth).
_DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


def normalize_oui(mac: str) -> str | None:
    """First 3 octets of `mac` as 6 uppercase hex chars, or None if it
    doesn't contain enough hex digits to form one. Accepts any of the
    common separator styles (colon, dash, dot) or none at all, since
    that's the only part of a MAC that varies across sources in this
    codebase (`ip neigh` output, vendor APIs, manual entry)."""
    hex_digits = "".join(ch for ch in mac if ch in "0123456789abcdefABCDEF")
    if len(hex_digits) < 6:
        return None
    return hex_digits[:6].upper()


def parse_oui_csv(text: str) -> dict[str, str]:
    """Parses the IEEE MA-L registry CSV (columns: Registry,Assignment,
    Organization Name,Organization Address) into {6-hex-OUI: org name}."""
    table: dict[str, str] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        assignment = (row.get("Assignment") or "").strip().upper()
        org = (row.get("Organization Name") or "").strip()
        if len(assignment) == 6 and org:
            table[assignment] = org
    return table


async def download_oui_csv(timeout: float = DOWNLOAD_TIMEOUT_SECONDS) -> str:
    async with httpx.AsyncClient(timeout=timeout, headers=_DOWNLOAD_HEADERS) as client:
        response = await client.get(IEEE_OUI_CSV_URL)
        response.raise_for_status()
        return response.text


@dataclass
class OuiStatus:
    entry_count: int
    updated_at: datetime.datetime | None


class OuiRegistry:
    """In-memory OUI table backed by a local cache file. Lazily loaded from
    disk on first lookup/status call; refreshed only by an explicit
    `update()`."""

    def __init__(self, settings: Settings) -> None:
        self._cache_path: Path = settings.data_dir / CACHE_FILENAME
        self._table: dict[str, str] = {}
        self._updated_at: datetime.datetime | None = None
        self._loaded_from_disk = False

    def _ensure_loaded(self) -> None:
        if self._loaded_from_disk:
            return
        self._loaded_from_disk = True
        if not self._cache_path.exists():
            return
        try:
            text = self._cache_path.read_text()
        except OSError:
            logger.warning("oui_cache_read_failed", path=str(self._cache_path))
            return
        self._table = parse_oui_csv(text)
        self._updated_at = datetime.datetime.fromtimestamp(
            self._cache_path.stat().st_mtime, tz=datetime.UTC
        )

    def lookup(self, mac: str | None) -> str | None:
        if not mac:
            return None
        self._ensure_loaded()
        oui = normalize_oui(mac)
        if oui is None:
            return None
        return self._table.get(oui)

    def status(self) -> OuiStatus:
        self._ensure_loaded()
        return OuiStatus(entry_count=len(self._table), updated_at=self._updated_at)

    async def update(self) -> OuiStatus:
        text = await download_oui_csv()
        table = parse_oui_csv(text)

        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(text)

        self._table = table
        self._updated_at = datetime.datetime.now(datetime.UTC)
        self._loaded_from_disk = True
        logger.info("oui_registry_updated", entry_count=len(table))
        return self.status()


@lru_cache
def get_oui_registry() -> OuiRegistry:
    return OuiRegistry(get_settings())
