import pytest

from app.integrations.generic_ssh import parsers


def test_parse_loadavg() -> None:
    result = parsers.parse_loadavg("0.10 0.20 0.30 1/200 12345\n")
    assert result == {"load1": 0.10, "load5": 0.20, "load15": 0.30}


def test_parse_loadavg_malformed_returns_empty() -> None:
    assert parsers.parse_loadavg("garbage") == {}


def test_parse_meminfo() -> None:
    text = "MemTotal:       16384000 kB\nMemAvailable:    8192000 kB\nOther: 1 kB\n"
    result = parsers.parse_meminfo(text)
    assert result["mem_total_kb"] == 16384000
    assert result["mem_used_percent"] == 50.0


def test_parse_meminfo_missing_total_returns_empty() -> None:
    assert parsers.parse_meminfo("garbage: not real\n") == {}


def test_parse_diskfree_root_mount() -> None:
    text = "Filesystem 1B-blocks Used Available Use% Mounted on\n/dev/sda1 100 50 50 50% /\n"
    assert parsers.parse_diskfree(text) == {"disk_used_percent": 50.0}


def test_parse_diskfree_ignores_non_root_mounts() -> None:
    text = (
        "Filesystem 1B-blocks Used Available Use% Mounted on\n"
        "/dev/sda1 100 90 10 90% /boot\n"
    )
    assert parsers.parse_diskfree(text) == {}


def test_parse_windows_cpu() -> None:
    assert parsers.parse_windows_cpu("\r\nLoadPercentage=42\r\n\r\n") == {"load1": 42.0}


def test_parse_windows_cpu_missing_value_returns_empty() -> None:
    assert parsers.parse_windows_cpu("\r\n\r\n") == {}


def test_parse_windows_meminfo() -> None:
    text = "\r\nFreePhysicalMemory=2097152\r\nTotalVisibleMemorySize=8388608\r\n\r\n"
    result = parsers.parse_windows_meminfo(text)
    assert result["mem_total_kb"] == 8388608.0
    assert result["mem_used_percent"] == pytest.approx(75.0)


def test_parse_windows_meminfo_missing_fields_returns_empty() -> None:
    assert parsers.parse_windows_meminfo("garbage") == {}


def test_parse_windows_diskfree() -> None:
    text = "\r\nFreeSpace=40000000000\r\nSize=100000000000\r\n\r\n"
    assert parsers.parse_windows_diskfree(text) == {"disk_used_percent": pytest.approx(60.0)}


def test_parse_windows_diskfree_missing_fields_returns_empty() -> None:
    assert parsers.parse_windows_diskfree("garbage") == {}
