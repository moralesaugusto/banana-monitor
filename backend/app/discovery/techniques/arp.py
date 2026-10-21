from app.discovery.techniques.subprocess_runner import SubprocessRunner, default_subprocess_runner


async def get_arp_table(runner: SubprocessRunner = default_subprocess_runner) -> dict[str, str]:
    """Maps IP -> MAC from `ip neigh` output, e.g. '192.168.1.10 dev eth0 lladdr aa:bb:.. REACHABLE'."""
    returncode, stdout, _ = await runner(["ip", "neigh"])
    table: dict[str, str] = {}
    if returncode != 0:
        return table

    for line in stdout.splitlines():
        parts = line.split()
        if not parts or "lladdr" not in parts:
            continue
        mac_index = parts.index("lladdr") + 1
        if mac_index < len(parts):
            table[parts[0]] = parts[mac_index]
    return table
