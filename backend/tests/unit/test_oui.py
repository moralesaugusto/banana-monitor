import datetime

import pytest

from app.config import get_settings
from app.discovery.oui import OuiRegistry, normalize_oui, parse_oui_csv

SAMPLE_CSV = (
    "Registry,Assignment,Organization Name,Organization Address\n"
    'MA-L,9C4E36,"Raspberry Pi Trading Ltd",Cambridge UK\n'
    'MA-L,B827EB,"Raspberry Pi Foundation",Cambridge UK\n'
    'MA-L,00E04C,"Realtek Semiconductor Corp.",Taiwan\n'
)


def test_normalize_oui_handles_common_separator_styles() -> None:
    assert normalize_oui("9c:4e:36:aa:bb:cc") == "9C4E36"
    assert normalize_oui("9c-4e-36-aa-bb-cc") == "9C4E36"
    assert normalize_oui("9c4e.36aa.bbcc") == "9C4E36"
    assert normalize_oui("9C4E36AABBCC") == "9C4E36"


def test_normalize_oui_rejects_too_short_input() -> None:
    assert normalize_oui("9c:4e") is None
    assert normalize_oui("") is None


def test_parse_oui_csv_extracts_assignment_and_org() -> None:
    table = parse_oui_csv(SAMPLE_CSV)
    assert table == {
        "9C4E36": "Raspberry Pi Trading Ltd",
        "B827EB": "Raspberry Pi Foundation",
        "00E04C": "Realtek Semiconductor Corp.",
    }


def test_parse_oui_csv_skips_malformed_rows() -> None:
    csv_text = (
        "Registry,Assignment,Organization Name,Organization Address\n"
        "MA-L,,Missing Assignment,Nowhere\n"
        "MA-L,ABCDEF,,Nowhere\n"
    )
    assert parse_oui_csv(csv_text) == {}


@pytest.mark.asyncio
async def test_registry_lookup_before_any_update_returns_none() -> None:
    registry = OuiRegistry(get_settings())
    assert registry.lookup("9c:4e:36:aa:bb:cc") is None
    status = registry.status()
    assert status.entry_count == 0
    assert status.updated_at is None


@pytest.mark.asyncio
async def test_registry_update_downloads_parses_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_download(timeout: float = 30.0) -> str:
        return SAMPLE_CSV

    monkeypatch.setattr("app.discovery.oui.download_oui_csv", fake_download)

    registry = OuiRegistry(get_settings())
    status = await registry.update()

    assert status.entry_count == 3
    assert isinstance(status.updated_at, datetime.datetime)
    assert registry.lookup("9c:4e:36:11:22:33") == "Raspberry Pi Trading Ltd"
    assert registry.lookup("aa:bb:cc:dd:ee:ff") is None
    assert registry.lookup(None) is None


@pytest.mark.asyncio
async def test_registry_loads_from_disk_cache_written_by_a_previous_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_download(timeout: float = 30.0) -> str:
        return SAMPLE_CSV

    monkeypatch.setattr("app.discovery.oui.download_oui_csv", fake_download)

    settings = get_settings()
    await OuiRegistry(settings).update()

    # A fresh instance (e.g. after a restart) picks up the cache file without
    # ever calling update() itself.
    reloaded = OuiRegistry(settings)
    assert reloaded.lookup("B827EB112233") == "Raspberry Pi Foundation"
    assert reloaded.status().entry_count == 3
