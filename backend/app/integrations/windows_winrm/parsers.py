import contextlib


def parse_health(text: str) -> tuple[dict[str, float], str | None]:
    """Reads the `key=value` lines HEALTH_SCRIPT prints; returns (metrics, hostname)."""
    fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    metrics: dict[str, float] = {}
    hostname = fields.get("hostname", "").strip() or None
    with contextlib.suppress(KeyError, ValueError):
        metrics["cpu_percent"] = float(fields["cpu"])
    with contextlib.suppress(KeyError, ValueError):
        total_kb, free_kb = (float(v) for v in fields["mem"].split())
        if total_kb:
            metrics["mem_total_kb"] = total_kb
            metrics["mem_used_percent"] = (total_kb - free_kb) / total_kb * 100
    with contextlib.suppress(KeyError, ValueError):
        size, free = (float(v) for v in fields["disk"].split())
        if size:
            metrics["disk_used_percent"] = (size - free) / size * 100
    return metrics, hostname
