"""What an agent may run on a host it inspects. Pure functions: each returns the checked command or raises
ValueError with the reason.

The commands an agent writes reach a remote shell, so the check is a character whitelist first (no quotes,
pipes, redirects, substitution or globbing can be spelled at all), then a per-program rule (read-only
programs only, with the options that write or execute removed), then a denylist of secret files."""

import re

MAX_COMMAND_LENGTH = 300
MAX_TOKENS = 30

_LINUX_CHARS = re.compile(r"^[A-Za-z0-9_./:=,@%+\- ]+$")
_WINDOWS_CHARS = re.compile(r"^[A-Za-z0-9_./\\:=,%+\- ]+$")

_SECRET_PATHS = re.compile(
    r"(/etc/(shadow|gshadow|sudoers|ssh/ssh_host_[a-z0-9_]+_key)(-|\.bak)?$"
    r"|/etc/ssl/private|/\.gnupg|/\.aws|/\.kube"
    r"|/\.ssh/(?!(authorized_keys|known_hosts)$)(?!.*\.pub$)"
    r"|^/proc/[^/]+/(environ|mem)$"
    r"|\.(pem|key|p12|pfx|kdbx)$|master\.key|credentials\.db)"
)
_SAFE_RECURSIVE_ROOTS = ("/var/log", "/tmp", "/var/spool/cron", "/etc/cron")
_RECURSIVE = {"-r", "-R", "--recursive", "--dereference-recursive"}

_PLAIN = [
    "uname",
    "uptime",
    "free",
    "df",
    "vmstat",
    "who",
    "w",
    "last",
    "lastb",
    "id",
    "getent",
    "lsmod",
    "lsblk",
    "lsof",
    "cat",
    "head",
    "tail",
    "ls",
    "stat",
    "wc",
    "du",
    "zcat",
    "sha256sum",
    "sha1sum",
    "md5sum",
    "strings",
    "find",
    "journalctl",
    "date",
]
_SUBCOMMANDS: dict[str, set[str]] = {
    "systemctl": {
        "status",
        "list-units",
        "list-timers",
        "list-unit-files",
        "is-active",
        "is-enabled",
        "is-failed",
        "show",
        "cat",
    },
    "ip": {"addr", "address", "a", "link", "route", "r", "neigh", "neighbor"},
    "apt": {"list"},
    "apt-get": {"upgrade", "dist-upgrade", "check"},
    "dnf": {"check-update", "list", "info", "updateinfo"},
    "yum": {"check-update", "list", "info", "updateinfo"},
}
_DENIED: dict[str, re.Pattern[str]] = {
    "journalctl": re.compile(
        r"^(-f|--(rotate|vacuum-.*|flush|sync|relinquish-var|smart-relinquish-var|setup-keys|"
        r"update-catalog|follow))$"
    ),
    "tail": re.compile(r"^(-f|-F|--follow.*)$"),
    "find": re.compile(r"^-(exec|execdir|ok|okdir|delete|fprint|fprint0|fprintf|fls)$"),
    "date": re.compile(r"^(-s|--set.*)$"),
    "ip": re.compile(r"^(set|add|del|delete|flush|change|replace|append|exec|netns)$"),
    "ss": re.compile(r"^(-[A-Za-z]*K[A-Za-z]*|--kill)$"),
    "file": re.compile(r"^(-C|--compile|-m|--magic-file.*)$"),
    "systemctl": re.compile(r"^(--user|-H|--host.*|-M|--machine.*)$"),
}
_OTHER = {"ps", "ss", "file", "grep", "zgrep", "dpkg", "rpm", "crontab", "hostname"}
_SIMULATE = {"-s", "--simulate", "--dry-run", "--just-print"}


class PolicyError(ValueError):
    pass


def _tokens(command: str, chars: re.Pattern[str]) -> list[str]:
    command = command.strip()
    if not command or len(command) > MAX_COMMAND_LENGTH:
        raise PolicyError(f"a command of 1-{MAX_COMMAND_LENGTH} characters is required")
    if not chars.match(command):
        raise PolicyError(
            "only letters, digits and _ . / : = , @ % + - are allowed (no quotes, pipes, redirects, "
            "substitution, globbing or newlines)"
        )
    tokens = command.split()
    if len(tokens) > MAX_TOKENS:
        raise PolicyError(f"at most {MAX_TOKENS} words")
    return tokens


def _check_paths(tokens: list[str]) -> None:
    for token in tokens:
        value = token.split("=", 1)[-1]
        if ".." in value.split("/"):
            raise PolicyError("'..' is not allowed in paths")
        if _SECRET_PATHS.search(token) or _SECRET_PATHS.search(value):
            raise PolicyError(f"{token!r} names a file that may hold secrets")


def _check_subcommand(program: str, args: list[str]) -> None:
    subcommand = next((a for a in args if not a.startswith("-")), None)
    allowed = _SUBCOMMANDS[program]
    if subcommand not in allowed:
        raise PolicyError(f"{program} may only be used with: {', '.join(sorted(allowed))}")
    if program == "apt-get" and not _SIMULATE & set(args):
        raise PolicyError("apt-get may only simulate; add -s")


def check_linux(command: str) -> str:
    tokens = _tokens(command, _LINUX_CHARS)
    program, args = tokens[0], tokens[1:]
    if "/" in program:
        raise PolicyError("give the program name only, without a path")
    _check_paths(tokens)

    denied = _DENIED.get(program)
    if denied and any(denied.match(a) for a in args):
        raise PolicyError(f"that option of {program} writes, executes, follows or kills and is not allowed")

    if program in _SUBCOMMANDS:
        _check_subcommand(program, args)
    elif program == "ps":
        # BSD-style `ps e` / `ps auxe` prints each process's environment, which holds secrets.
        if any("environ" in a or re.fullmatch(r"[A-Za-z]*e[A-Za-z]*", a) for a in args):
            raise PolicyError("ps may not print process environments")
    elif program in {"grep", "zgrep"}:
        if _RECURSIVE & set(args) or any(re.match(r"^-[A-Za-z]*[rR][A-Za-z]*$", a) for a in args):
            paths = [a for a in args if a.startswith("/")]
            if not paths or not all(p.startswith(_SAFE_RECURSIVE_ROOTS) for p in paths):
                roots = ", ".join(_SAFE_RECURSIVE_ROOTS)
                raise PolicyError(f"recursive grep is limited to: {roots}")
    elif program == "dpkg":
        if not args or args[0] not in {
            "-l",
            "--list",
            "-s",
            "--status",
            "-L",
            "--listfiles",
            "-V",
            "--verify",
        }:
            raise PolicyError("dpkg may only list or query")
    elif program == "rpm":
        if not args or not re.match(r"^-(q[A-Za-z]*|V[A-Za-z]*)$", args[0]):
            raise PolicyError("rpm may only query or verify (-q..., -V)")
    elif program == "crontab":
        if args != ["-l"]:
            raise PolicyError("crontab may only be used as: crontab -l")
    elif program == "hostname":
        if any(not a.startswith("-") for a in args):
            raise PolicyError("hostname may not set a name")
    elif program not in _PLAIN and program not in _OTHER:
        known = sorted({*_PLAIN, *_SUBCOMMANDS, *_OTHER})
        raise PolicyError(f"{program!r} is not allowed; use one of: {', '.join(known)}")
    return " ".join(tokens)


_WINDOWS_CMDLETS = {
    "Get-Process",
    "Get-Service",
    "Get-EventLog",
    "Get-WinEvent",
    "Get-NetTCPConnection",
    "Get-NetIPAddress",
    "Get-NetFirewallRule",
    "Get-NetFirewallProfile",
    "Get-NetRoute",
    "Get-NetNeighbor",
    "Get-DnsClientCache",
    "Get-LocalUser",
    "Get-LocalGroup",
    "Get-LocalGroupMember",
    "Get-HotFix",
    "Get-ComputerInfo",
    "Get-CimInstance",
    "Get-ScheduledTask",
    "Get-ScheduledTaskInfo",
    "Get-ItemProperty",
    "Get-ChildItem",
    "Get-FileHash",
    "Get-Content",
    "Get-SmbShare",
    "Get-SmbSession",
    "Get-Date",
    "Get-PSDrive",
    "Get-Volume",
    "Get-Disk",
    "Get-MpComputerStatus",
    "Get-MpThreat",
    "Get-MpThreatDetection",
    "Get-AuthenticodeSignature",
}
_WINDOWS_DENIED_PARAMS = re.compile(
    r"^-(Credential|ComputerName|CimSession|Session|OutFile|OutVariable|ErrorVariable|Stream|Wait|"
    r"Recurse|Force)$",
    re.IGNORECASE,
)
_WINDOWS_SECRET_PATHS = re.compile(
    r"(\\config\\(SAM|SECURITY|SYSTEM|SOFTWARE)|ntds|\\\.ssh\\|\.(pem|key|p12|pfx|kdbx)$|"
    r"HKLM:?\\SAM|HKLM:?\\SECURITY|Credentials|master\.key|credentials\.db)",
    re.IGNORECASE,
)
WINDOWS_OUTPUT_SUFFIX = " | Out-String -Width 200"
"""Appended by the tool, never written by the model, so output is always plain text of bounded width."""


def check_windows(command: str) -> str:
    tokens = _tokens(command, _WINDOWS_CHARS)
    cmdlet, args = tokens[0], tokens[1:]
    if cmdlet not in _WINDOWS_CMDLETS:
        raise PolicyError(f"only these cmdlets are allowed: {', '.join(sorted(_WINDOWS_CMDLETS))}")
    for arg in args:
        if arg.startswith("-") and not re.match(r"^-[A-Za-z]+$", arg):
            raise PolicyError(f"{arg!r} is not a parameter name")
        if _WINDOWS_DENIED_PARAMS.match(arg):
            raise PolicyError(f"parameter {arg} is not allowed")
        if _WINDOWS_SECRET_PATHS.search(arg):
            raise PolicyError(f"{arg!r} names something that may hold secrets")
        if ".." in re.split(r"[\\/]", arg):
            raise PolicyError("'..' is not allowed in paths")
    return " ".join(tokens)


_PROXMOX_PATHS = [
    re.compile(p)
    for p in (
        r"^/version$",
        r"^/cluster/(status|resources|log|tasks)$",
        r"^/nodes$",
        r"^/nodes/[A-Za-z0-9_-]+/(status|qemu|lxc|tasks|syslog|time|version|disks/list|apt/update|apt/versions|services|network|netstat|storage)$",
        r"^/nodes/[A-Za-z0-9_-]+/(qemu|lxc)/[0-9]+/(status/current|config|snapshot)$",
    )
]


def check_proxmox_path(path: str) -> str:
    path = path.strip()
    if not any(p.match(path) for p in _PROXMOX_PATHS):
        raise PolicyError("this Proxmox API path is not allowed (read-only status, tasks, logs, updates)")
    return path
