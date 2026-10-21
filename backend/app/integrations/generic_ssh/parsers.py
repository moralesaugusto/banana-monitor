def parse_loadavg(text: str) -> dict[str, float]:
    parts = text.split()
    if len(parts) < 3:
        return {}
    return {"load1": float(parts[0]), "load5": float(parts[1]), "load15": float(parts[2])}


def parse_meminfo(text: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        fields = rest.strip().split()
        if not fields:
            continue
        try:
            values[key.strip()] = float(fields[0])
        except ValueError:
            continue

    total = values.get("MemTotal", 0.0)
    available = values.get("MemAvailable", 0.0)
    if not total:
        return {}
    return {
        "mem_total_kb": total,
        "mem_used_percent": (total - available) / total * 100,
    }


def parse_diskfree(text: str, mount_point: str = "/") -> dict[str, float]:
    for line in text.splitlines()[1:]:
        columns = line.split()
        if len(columns) < 6:
            continue
        use_percent, mount = columns[4], columns[5]
        if mount == mount_point:
            try:
                return {"disk_used_percent": float(use_percent.rstrip("%"))}
            except ValueError:
                return {}
    return {}


def _wmic_values(text: str) -> dict[str, str]:
    """`wmic ... get X,Y /value` prints `X=1\\r\\nY=2\\r\\n` (plus blank lines) - this is the shared
    parse for all three Windows commands below."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if value:
            values[key.strip()] = value
    return values


def parse_windows_cpu(text: str) -> dict[str, float]:
    """wmic has no direct equivalent of a Unix load average; LoadPercentage is an instantaneous CPU
    usage percent, reported under the same `load1` key so it shows up next to Linux hosts - callers
    should not compare the two as the same unit. No load5/load15 equivalent exists."""
    values = _wmic_values(text)
    try:
        return {"load1": float(values["LoadPercentage"])}
    except (KeyError, ValueError):
        return {}


def parse_windows_meminfo(text: str) -> dict[str, float]:
    values = _wmic_values(text)
    try:
        total = float(values["TotalVisibleMemorySize"])  # already KB, same unit as parse_meminfo's
        free = float(values["FreePhysicalMemory"])  # also KB
    except (KeyError, ValueError):
        return {}
    if not total:
        return {}
    return {"mem_total_kb": total, "mem_used_percent": (total - free) / total * 100}


def parse_windows_diskfree(text: str) -> dict[str, float]:
    values = _wmic_values(text)
    try:
        size = float(values["Size"])
        free = float(values["FreeSpace"])
    except (KeyError, ValueError):
        return {}
    if not size:
        return {}
    return {"disk_used_percent": (size - free) / size * 100}


def parse_linux_metrics(outputs: dict[str, str]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    metrics.update(parse_loadavg(outputs.get("loadavg", "")))
    metrics.update(parse_meminfo(outputs.get("meminfo", "")))
    metrics.update(parse_diskfree(outputs.get("diskfree", "")))
    return metrics


def parse_windows_metrics(outputs: dict[str, str]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    metrics.update(parse_windows_cpu(outputs.get("cpu", "")))
    metrics.update(parse_windows_meminfo(outputs.get("meminfo", "")))
    metrics.update(parse_windows_diskfree(outputs.get("diskfree", "")))
    return metrics


PARSERS_BY_OS = {"linux": parse_linux_metrics, "windows": parse_windows_metrics}
