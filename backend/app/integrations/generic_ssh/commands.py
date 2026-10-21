"""Static, parameterized command tables, one per detected OS family.

The plugin only ever executes commands from these tables verbatim - it never
builds a command string from user/config input, which is what keeps this
integration from being a vector for arbitrary remote code execution.

Linux and Windows (OpenSSH, cmd.exe as the default remote shell - see
Win32-OpenSSH's DefaultShell) are implemented. A BSD/Darwin/appliance SSH
host would need its own command set and parser (see parsers.py), which is a
small, separate addition once there's a real target to test it against.
Don't guess at one now.
"""

DETECT_OS_COMMAND = "uname -s"

LINUX_COMMANDS: dict[str, str] = {
    "loadavg": "cat /proc/loadavg",
    "meminfo": "cat /proc/meminfo",
    "diskfree": "df -P -B1",
    "hostname": "hostname",
}

WINDOWS_COMMANDS: dict[str, str] = {
    "cpu": "wmic cpu get loadpercentage /value",
    "meminfo": "wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /value",
    "diskfree": r"wmic logicaldisk where DeviceID='C:' get Size,FreeSpace /value",
    "hostname": "hostname",
}
"""cmd.exe builtins/wmic - Win32-OpenSSH's default shell for an incoming SSH session is cmd.exe, not
PowerShell, so these avoid needing a `powershell -Command` wrapper. wmic is deprecated since Windows
10 21H1 but still present through at least Windows 11 24H2; if a future Windows drops it, this needs
a CIM/PowerShell-based replacement."""

COMMANDS_BY_OS: dict[str, dict[str, str]] = {
    "linux": LINUX_COMMANDS,
    "windows": WINDOWS_COMMANDS,
    # "darwin": {...} - not implemented: `uname -s` reports it, but BSD/macOS
    # `df`/`vm_stat` output differs from GNU coreutils and needs its own
    # parser. Add the command set here and a matching branch in parsers.py
    # when there's a real target to validate it against.
}

COMMANDS = LINUX_COMMANDS  # backward-compatible alias for any direct import
